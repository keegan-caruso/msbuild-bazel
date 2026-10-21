using System.Collections.Concurrent;
using System.Text.Json;
using Microsoft.Build.Execution;
using Microsoft.Build.Framework;
using Microsoft.Build.Graph;
#if STABLE_PROJECT_CACHE
using Microsoft.Build.ProjectCache;
#else
using Microsoft.Build.Experimental.ProjectCache;
#endif
using RulesMSBuild.ProjectCache;

namespace RulesMSBuild.ProjectSync;

internal sealed record QualificationTarget(string Name, QualificationResult[] Items);
internal sealed record QualificationResult(string Include, Dictionary<string, string> Metadata);
internal sealed record QualificationMetadata(QualificationState State, QualificationTarget[] Targets, Dictionary<string, int> Modes);
internal sealed record QualificationManifest(string Fingerprint, Dictionary<string, string> Files);

// SDK targets still execute on misses. Hits restore owned artifacts and the
// resolved state that ordinary Build cache results alone do not provide.
internal sealed class QualificationCache : ProjectCachePluginBase, IDisposable
{
    private readonly QualificationInputs inputs;
    private readonly string directory;
    private readonly SnapshotPayloads payloads;
    private readonly RemoteSnapshotStore? remote;
    private readonly ConcurrentDictionary<ProjectGraphNode, (string Fingerprint, string[] Targets)> requests = new();
    private readonly ConcurrentDictionary<ProjectGraphNode, QualificationState> states = new();
    private readonly ConcurrentDictionary<ProjectGraphNode, byte> hits = new();
    private int uncacheable;

    internal QualificationCache(QualificationInputs inputs, QualificationOptions options)
    {
        this.inputs = inputs;
        directory = Path.GetFullPath(options.Directory);
        Directory.CreateDirectory(directory);
        if (new DirectoryInfo(directory).LinkTarget is not null)
        {
            throw new InvalidDataException("Qualification cache directory must not be a symlink");
        }
        payloads = new SnapshotPayloads(directory);
        remote = options.Url is null ? null : new RemoteSnapshotStore(new Uri(options.Url.TrimEnd('/') + "/"),
            bearerToken: Environment.GetEnvironmentVariable("RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN"), contentStore: payloads);
    }

    public override Task BeginBuildAsync(CacheContext context, PluginLoggerBase logger, CancellationToken cancellationToken) => Task.CompletedTask;
    public override Task EndBuildAsync(PluginLoggerBase logger, CancellationToken cancellationToken) => Task.CompletedTask;

    public override async Task<CacheResult> GetCacheResultAsync(BuildRequestData request, PluginLoggerBase logger, CancellationToken cancellationToken)
    {
        var key = request.ProjectFullPath + "|" + string.Join(";", request.GlobalProperties.OrderBy(property => property.Name, StringComparer.Ordinal).Select(property => property.Name + "=" + property.EvaluatedValue));
        var node = inputs.Nodes[key];
        if (!request.TargetNames.Contains("Build", StringComparer.OrdinalIgnoreCase) || !inputs.Eligible.Contains(node))
        {
            return CacheResult.IndicateNonCacheHit(CacheResultType.CacheNotApplicable);
        }
        var fingerprint = inputs.Fingerprint(node, request.TargetNames);
        requests[node] = (fingerprint, request.TargetNames.ToArray());
        var entry = Path.Combine(directory, fingerprint);
        var manifestPath = Path.Combine(entry, "manifest.json");
        if (!File.Exists(manifestPath) && remote is not null)
        {
            await remote.FetchAsync(fingerprint, entry, cancellationToken);
        }
        if (!File.Exists(manifestPath))
        {
            return CacheResult.IndicateNonCacheHit(CacheResultType.CacheMiss);
        }
        var manifest = JsonSerializer.Deserialize<QualificationManifest>(File.ReadAllText(manifestPath))
            ?? throw new InvalidDataException("Missing qualification manifest");
        if (manifest.Fingerprint != fingerprint || !manifest.Files.ContainsKey("state.json"))
        {
            throw new InvalidDataException("Invalid qualification manifest");
        }
        if (SnapshotPayloads.Digest(Safe(entry, "state.json")) != manifest.Files["state.json"])
        {
            throw new InvalidDataException("Corrupt qualification snapshot: state.json");
        }
        var metadata = JsonSerializer.Deserialize<QualificationMetadata>(File.ReadAllText(Safe(entry, "state.json")))
            ?? throw new InvalidDataException("Missing qualification state");
        if (!metadata.Targets.Select(target => target.Name).SequenceEqual(Targets(node), StringComparer.OrdinalIgnoreCase) ||
            !metadata.Modes.Keys.Order(StringComparer.Ordinal).SequenceEqual(manifest.Files.Keys.Where(path => path != "state.json").Order(StringComparer.Ordinal)))
        {
            throw new InvalidDataException("Invalid qualification targets or artifact set");
        }
        foreach (var (path, mode) in metadata.Modes)
        {
            if (!path.StartsWith("outputs/", StringComparison.Ordinal) || !inputs.Owns(node, path[8..]) || (mode & ~511) != 0)
            {
                throw new InvalidDataException("Unowned qualification artifact: " + path);
            }
            var target = inputs.Resolve(path[8..]);
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            try
            {
                SyncFiles.Copy(Safe(entry, path), target, overwrite: true, expectedDigest: manifest.Files[path]);
            }
            catch (InvalidDataException error)
            {
                throw new InvalidDataException("Corrupt qualification snapshot: " + path, error);
            }
            if (!OperatingSystem.IsWindows())
            {
                File.SetUnixFileMode(target, (UnixFileMode)mode);
            }
        }
        states[node] = metadata.State;
        hits[node] = 0;
        return CacheResult.IndicateCacheHit(metadata.Targets.Select(target => new PluginTargetResult(target.Name,
            target.Items.Select(item =>
            {
                ITaskItem2 restored = new CachedTargetItem(Microsoft.Build.Evaluation.ProjectCollection.Escape(item.Include));
                foreach (var (name, value) in item.Metadata)
                {
                    restored.SetMetadataValueLiteral(name, value);
                }
                return restored;
            }).ToArray(), BuildResultCode.Success)).ToArray());
    }

    internal QualificationState State(ProjectGraphNode node, GraphBuildResult result) => states.TryGetValue(node, out var state) ? state :
        QualificationState.From(result.ResultsByNode.GetValueOrDefault(node)?.ProjectStateAfterBuild
            ?? throw new InvalidDataException("Missing resolved compiler state: " + node.ProjectInstance.FullPath));

    internal void Save(GraphBuildResult result, int compilations)
    {
        foreach (var (node, request) in requests)
        {
            var fingerprint = request.Fingerprint;
            if (hits.ContainsKey(node))
            {
                continue;
            }
            var build = result.ResultsByNode[node];
            var files = inputs.Files(node).Order(StringComparer.Ordinal).ToArray();
            foreach (var file in files)
            {
                if (new FileInfo(file).LinkTarget is not null)
                {
                    throw new InvalidDataException("Qualification output symlink: " + file);
                }
            }
            if (files.Any(path => !inputs.Owns(node, inputs.Relative(path))))
            {
                uncacheable++;
                continue;
            }
            var stage = Path.Combine(directory, ".pending-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(stage);
            try
            {
                var digests = new Dictionary<string, string>(StringComparer.Ordinal);
                var modes = new Dictionary<string, int>(StringComparer.Ordinal);
                foreach (var file in files)
                {
                    var path = "outputs/" + inputs.Relative(file);
                    var digest = SnapshotPayloads.Digest(file);
                    payloads.Store(file, digest, Safe(stage, path));
                    digests.Add(path, digest);
                    modes.Add(path, OperatingSystem.IsWindows() ? 0 : (int)File.GetUnixFileMode(file) & 511);
                }
                var targets = Targets(node).Select(name =>
                {
                    if (!build.ResultsByTarget.TryGetValue(name, out var target) || target.ResultCode == TargetResultCode.Failure)
                    {
                        throw new InvalidDataException("Missing qualification target result: " + name);
                    }
                    return new QualificationTarget(name, target.Items.Select(item => new QualificationResult(item.ItemSpec,
                        item.CloneCustomMetadata().Keys.Cast<string>().Order(StringComparer.Ordinal).ToDictionary(key => key, key => item.GetMetadata(key)))).ToArray());
                }).ToArray();
                var state = State(node, result);
                var stateFile = Safe(stage, "state.json");
                File.WriteAllText(stateFile, JsonSerializer.Serialize(new QualificationMetadata(state, targets, modes)));
                digests.Add("state.json", SnapshotPayloads.Digest(stateFile));
                File.WriteAllText(Path.Combine(stage, "manifest.json"), JsonSerializer.Serialize(new QualificationManifest(fingerprint, digests)));
                var destination = Path.Combine(directory, fingerprint);
                try
                {
                    Directory.Move(stage, destination);
                }
                catch (IOException) when (Directory.Exists(destination))
                {
                    // Initial qualification and independent producers can finish together.
                    // Portable keys must describe identical bytes and resolved state.
                    if (File.ReadAllText(Path.Combine(destination, "manifest.json")) != File.ReadAllText(Path.Combine(stage, "manifest.json")))
                    {
                        throw new InvalidDataException("Conflicting qualification snapshot: " + fingerprint);
                    }
                }
                remote?.PublishAsync(fingerprint, destination, CancellationToken.None).GetAwaiter().GetResult();
            }
            finally
            {
                if (Directory.Exists(stage))
                {
                    Directory.Delete(stage, true);
                }
            }
        }
        Console.Error.WriteLine("PROJECT_SYNC_CACHE " + JsonSerializer.Serialize(new
        {
            hits = hits.Count,
            misses = requests.Count - hits.Count,
            uncacheable,
            compilations
        }));
    }

    private string[] Targets(ProjectGraphNode node) => requests[node].Targets.Concat(node.ProjectInstance.InitialTargets).Distinct(StringComparer.OrdinalIgnoreCase).ToArray();
    private static string Safe(string root, string path)
    {
        var target = Path.Combine(root, WorkspaceView.Safe(path));
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        for (var parent = Path.GetDirectoryName(target); parent is not null && parent.Length >= root.Length; parent = Path.GetDirectoryName(parent))
        {
            if (new DirectoryInfo(parent).LinkTarget is not null)
            {
                throw new InvalidDataException("Qualification cache directory symlink: " + parent);
            }
        }
        return target;
    }
    public void Dispose() => remote?.Dispose();
}
