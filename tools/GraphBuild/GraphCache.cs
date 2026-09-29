using System.Collections.Concurrent;
using System.Text.Json;
using Microsoft.Build.Execution;
using Microsoft.Build.Framework;
using Microsoft.Build.Graph;
using Microsoft.Build.ProjectCache;
using RulesMSBuild.ProjectCache;
using TaskItem = Microsoft.Build.Utilities.TaskItem;

namespace RulesMSBuild.GraphBuild;

internal sealed record ResultItem(string Include, Dictionary<string, string> Metadata);
internal sealed record TargetOutput(string Name, ResultItem[] Items);
internal sealed record ProjectSnapshot(string Fingerprint, Dictionary<string, string> Files,
    Dictionary<string, string> ProjectCopies, TargetOutput[] Targets, Dictionary<string, int> UnixModes);

internal sealed class GraphCache(GraphInputs inputs, string cache, bool read, RemoteSnapshotStore? remote, FileMaterializer materializer) : ProjectCachePluginBase
{
    private readonly Dictionary<string, ProjectGraphNode> nodes = inputs.Graph.ProjectNodes.ToDictionary(n => GraphInputs.Key(n.ProjectInstance));
    private readonly Dictionary<ProjectGraphNode, string[]> outputDirectories = inputs.Graph.ProjectNodes.ToDictionary(node => node, node => inputs.OutputDirectories(node).ToArray());
    private readonly ConcurrentDictionary<ProjectGraphNode, HashSet<ProjectGraphNode>> dependencies = new();
    private readonly ConcurrentDictionary<ProjectGraphNode, string[]> outputFiles = new();
    private readonly ConcurrentDictionary<string, Lazy<string>> outputDigests = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, bool> dependencyPresence = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, string> fingerprints = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, string[]> requestedTargets = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, ProjectSnapshot> hits = new(StringComparer.Ordinal);
    internal int Hits;
    internal int Misses;

    public override Task BeginBuildAsync(CacheContext context, PluginLoggerBase logger, CancellationToken cancellationToken) => Task.CompletedTask;
    public override Task EndBuildAsync(PluginLoggerBase logger, CancellationToken cancellationToken) => Task.CompletedTask;

    public override async Task<CacheResult> GetCacheResultAsync(BuildRequestData request, PluginLoggerBase logger, CancellationToken cancellationToken)
    {
        var key = request.ProjectFullPath + "|" + string.Join(";", request.GlobalProperties.OrderBy(p => p.Name, StringComparer.Ordinal).Select(p => p.Name + "=" + p.EvaluatedValue));
        var node = nodes[key];
        if (node.ProjectInstance.GetPropertyValue("TargetPath").Length == 0)
        {
            return CacheResult.IndicateNonCacheHit(CacheResultType.CacheNotApplicable);
        }
        var fingerprint = Fingerprint(node, request.TargetNames.ToArray());
        fingerprints[key] = fingerprint;
        requestedTargets[key] = request.TargetNames.ToArray();
        var directory = Path.Combine(cache, fingerprint);
        var manifest = Path.Combine(directory, "manifest.json");
        if (read && !File.Exists(manifest) && remote is not null)
        {
            await remote.FetchAsync(fingerprint, directory, cancellationToken);
        }
        if (read && File.Exists(manifest))
        {
            var snapshot = JsonSerializer.Deserialize<ProjectSnapshot>(File.ReadAllText(manifest))
                ?? throw new InvalidDataException("Empty graph snapshot");
            Validate(node, snapshot, fingerprint, directory, request.TargetNames.ToArray());
            foreach (var (relative, _) in snapshot.Files)
            {
                materializer.Copy(Path.Combine(directory, relative), inputs.Files.Resolve(relative));
                if (!OperatingSystem.IsWindows())
                {
                    File.SetUnixFileMode(inputs.Files.Resolve(relative), (UnixFileMode)snapshot.UnixModes[relative]);
                }
            }
            foreach (var (relative, producer) in snapshot.ProjectCopies)
            {
                materializer.Copy(inputs.Files.Resolve(producer), inputs.Files.Resolve(relative));
            }
            hits[key] = snapshot;
            Interlocked.Increment(ref Hits);
            var results = snapshot.Targets.Select(target => new PluginTargetResult(target.Name,
                target.Items.Select(RestoreItem).ToArray(), BuildResultCode.Success)).ToArray();
            return CacheResult.IndicateCacheHit(results);
        }
        Interlocked.Increment(ref Misses);
        return CacheResult.IndicateNonCacheHit(CacheResultType.CacheMiss);
    }

    internal async Task SaveAsync(GraphBuildResult result)
    {
        foreach (var (node, build) in result.ResultsByNode)
        {
            var key = GraphInputs.Key(node.ProjectInstance);
            if (hits.ContainsKey(key) || !fingerprints.TryGetValue(key, out var fingerprint))
            {
                continue;
            }
            var files = new Dictionary<string, string>(StringComparer.Ordinal);
            var modes = new Dictionary<string, int>(StringComparer.Ordinal);
            var copies = new Dictionary<string, string>(StringComparer.Ordinal);
            var staging = Path.Combine(cache, ".staging-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(staging);
            foreach (var file in OutputFiles(node))
            {
                var relative = Path.GetRelativePath(inputs.Files.Root, file);
                var digest = OutputDigest(file);
                var producer = (inputs.For(node).DependencyCopies ?? []).GetValueOrDefault(relative);
                if (producer is not null)
                {
                    var source = inputs.Files.Resolve(producer);
                    if (!IsDependencyOutput(node, source) || OutputDigest(source) != digest)
                    {
                        throw new InvalidDataException("Declared dependency copy does not match its producer: " + relative);
                    }
                    copies.Add(relative, producer);
                }
                else
                {
                    files.Add(relative, digest);
                    modes.Add(relative, OperatingSystem.IsWindows() ? 0 : (int)File.GetUnixFileMode(file));
                    materializer.Copy(file, Path.Combine(staging, relative));
                }
            }
            var targets = requestedTargets[key].Select(name =>
            {
                if (!build.ResultsByTarget.TryGetValue(name, out var target) || target.ResultCode != TargetResultCode.Success)
                {
                    throw new InvalidDataException("Missing successful target result: " + name);
                }
                return new TargetOutput(name, target.Items.Select(item => new ResultItem(item.ItemSpec,
                    Metadata(item))).ToArray());
            }).ToArray();
            var snapshot = new ProjectSnapshot(fingerprint, files, copies, targets, modes);
            File.WriteAllText(Path.Combine(staging, "manifest.json"), JsonSerializer.Serialize(snapshot));
            var destination = Path.Combine(cache, fingerprint);
            if (Directory.Exists(destination))
            {
                var existing = JsonSerializer.Deserialize<ProjectSnapshot>(File.ReadAllText(Path.Combine(destination, "manifest.json")))!;
                if (JsonSerializer.Serialize(existing) != JsonSerializer.Serialize(snapshot))
                {
                    throw new InvalidDataException("Conflicting graph snapshot: " + fingerprint);
                }
                Directory.Delete(staging, recursive: true);
            }
            else
            {
                Directory.Move(staging, destination);
            }
            if (remote is not null)
            {
                await remote.PublishAsync(fingerprint, destination, CancellationToken.None);
            }
        }
    }

    private string Fingerprint(ProjectGraphNode node, string[] targets)
    {
        var records = new List<string> { "graph-snapshot-v1", inputs.Fingerprint(node) };
        records.AddRange(targets.Select(t => "target:" + t));
        // Adding or removing a PDB/XML copy changes the consumer's output set,
        // even when its compiler-facing reference assemblies are unchanged.
        records.AddRange((inputs.For(node).DependencyCopies ?? []).OrderBy(copy => copy.Key, StringComparer.Ordinal)
            .Select(copy => "copy-present:" + copy.Key + "=" + dependencyPresence.GetOrAdd(copy.Value,
                path => File.Exists(inputs.Files.Resolve(path)))));
        // SDK compilation can see transitive reference assemblies. A grandchild
        // API change must invalidate those consumers even if its parent API stays put.
        IEnumerable<ProjectGraphNode> references = inputs.For(node).ReferenceBoundary &&
            !node.ProjectInstance.GetPropertyValue("DisableTransitiveProjectReferences").Equals("true", StringComparison.OrdinalIgnoreCase)
            ? DependencyNodes(node) : node.ProjectReferences;
        foreach (var reference in references.OrderBy(n => GraphInputs.Key(n.ProjectInstance), StringComparer.Ordinal))
        {
            var authored = node.ProjectInstance.GetItems("ProjectReference").Where(item =>
                Path.GetFullPath(item.EvaluatedInclude.Replace('\\', '/'), Path.GetDirectoryName(node.ProjectInstance.FullPath)!) == reference.ProjectInstance.FullPath);
            var implementation = !inputs.For(node).ReferenceBoundary || authored.Any(item => item.GetMetadataValue("OutputItemType").Length != 0 ||
                item.GetMetadataValue("ReferenceOutputAssembly").Equals("false", StringComparison.OrdinalIgnoreCase) ||
                item.GetMetadataValue("Targets").Length != 0);
            if (implementation)
            {
                records.Add("dependency-inputs:" + inputs.Fingerprint(reference));
                records.AddRange(DependencyNodes(reference).Select(inputs.Fingerprint).Order(StringComparer.Ordinal));
                records.AddRange(OutputFiles(reference).Select(path => path + ":" + OutputDigest(path)));
            }
            else
            {
                var project = reference.ProjectInstance;
                var path = project.GetPropertyValue("TargetRefPath");
                if (path.Length == 0)
                {
                    path = Path.Combine(project.GetPropertyValue("IntermediateOutputPath"), "ref", Path.GetFileName(TargetPath(reference)));
                }
                path = Path.GetFullPath(path, Path.GetDirectoryName(project.FullPath)!);
                if (!File.Exists(path))
                {
                    path = TargetPath(reference);
                }
                if (!File.Exists(path))
                {
                    throw new InvalidDataException("Missing dependency result: " + path);
                }
                records.Add(GraphInputs.Key(project) + ":" + OutputDigest(path));
            }
        }
        return ContractFiles.Hash(records);
    }

    private void Validate(ProjectGraphNode node, ProjectSnapshot snapshot, string fingerprint, string directory, string[] targets)
    {
        if (snapshot.Fingerprint != fingerprint || !snapshot.Targets.Select(t => t.Name).SequenceEqual(targets) ||
            !snapshot.Files.ContainsKey(Path.GetRelativePath(inputs.Files.Root, TargetPath(node))))
        {
            throw new InvalidDataException("Invalid graph snapshot contract");
        }
        foreach (var (relative, digest) in snapshot.Files)
        {
            Allowed(relative);
            if (ContractFiles.Digest(Path.Combine(directory, relative)) != digest)
            {
                throw new InvalidDataException("Corrupt graph snapshot: " + relative);
            }
        }
        foreach (var (relative, producer) in snapshot.ProjectCopies)
        {
            Allowed(relative);
            if ((inputs.For(node).DependencyCopies ?? []).GetValueOrDefault(relative) != producer || snapshot.Files.ContainsKey(relative) || !IsDependencyOutput(node, inputs.Files.Resolve(producer)))
            {
                throw new InvalidDataException("Invalid dependency copy: " + relative);
            }
        }
        void Allowed(string relative)
        {
            var path = inputs.Files.Resolve(relative);
            if (!outputDirectories[node].Any(dir => path.StartsWith(dir + Path.DirectorySeparatorChar, StringComparison.Ordinal)))
            {
                throw new InvalidDataException("Snapshot output escaped project ownership: " + relative);
            }
        }
    }

    private string OutputDigest(string path) => outputDigests.GetOrAdd(path, file => new Lazy<string>(() => ContractFiles.Digest(file))).Value;

    private bool IsDependencyOutput(ProjectGraphNode node, string path) => File.Exists(path) && DependencyNodes(node)
        .Any(dependency => outputDirectories[dependency].Any(directory => path.StartsWith(directory + Path.DirectorySeparatorChar, StringComparison.Ordinal)));

    // A project is queried only after its dependencies finish. Their disjoint
    // output trees are immutable for the rest of this graph invocation.
    private string[] OutputFiles(ProjectGraphNode node) => outputFiles.GetOrAdd(node, current => outputDirectories[current]
        .Where(Directory.Exists).SelectMany(dir => Directory.EnumerateFiles(dir, "*", SearchOption.AllDirectories))
        .Where(path => !path.EndsWith(".AssemblyReference.cache", StringComparison.Ordinal))
        .Select(path => inputs.Files.Resolve(Path.GetRelativePath(inputs.Files.Root, path)))
        .Distinct().Order(StringComparer.Ordinal).ToArray());

    private HashSet<ProjectGraphNode> DependencyNodes(ProjectGraphNode node) => dependencies.GetOrAdd(node, current =>
    {
        var visited = new HashSet<ProjectGraphNode>();
        var pending = new Stack<ProjectGraphNode>(current.ProjectReferences);
        while (pending.TryPop(out var dependency))
        {
            if (visited.Add(dependency))
            {
                foreach (var child in dependency.ProjectReferences)
                {
                    pending.Push(child);
                }
            }
        }
        return visited;
    });

    private static string TargetPath(ProjectGraphNode node) => Path.GetFullPath(node.ProjectInstance.GetPropertyValue("TargetPath"), Path.GetDirectoryName(node.ProjectInstance.FullPath)!);
    private static Dictionary<string, string> Metadata(ITaskItem item)
    {
        var metadata = item.CloneCustomMetadata();
        return metadata.Keys.Cast<string>().Order(StringComparer.Ordinal).ToDictionary(name => name, name => (string)metadata[name]!);
    }

    private static ITaskItem2 RestoreItem(ResultItem item)
    {
        ITaskItem2 result = new TaskItem(Microsoft.Build.Evaluation.ProjectCollection.Escape(item.Include));
        foreach (var (name, value) in item.Metadata)
        {
            result.SetMetadataValueLiteral(name, value);
        }
        return result;
    }
}
