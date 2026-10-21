using System.Collections.Concurrent;
using System.Security.Cryptography;
using System.Text;
using Microsoft.Build.Execution;
using Microsoft.Build.Graph;
using RulesMSBuild.ProjectCache;

namespace RulesMSBuild.ProjectSync;

internal sealed record QualificationOptions(string Directory, string? Url);
internal sealed record QualificationItem(string Include, string Subdirectory);
internal sealed record QualificationState(string TargetPath, string PublishDir, string[] References, QualificationItem[] Copies)
{
    internal static QualificationState From(ProjectInstance state) => new(state.GetPropertyValue("TargetPath"),
        state.GetPropertyValue("PublishDir"), state.GetItems("ReferencePathWithRefAssemblies").Select(item => item.EvaluatedInclude).ToArray(),
        state.GetItems("ReferenceCopyLocalPaths").Select(item => new QualificationItem(item.EvaluatedInclude, item.GetMetadataValue("DestinationSubDirectory"))).ToArray());
}

// Inputs are captured before Build mutates any ProjectInstance. Dependency keys
// deliberately include source inputs, not guessed reference-assembly boundaries.
internal sealed class QualificationInputs
{
    private readonly ConcurrentDictionary<string, Lazy<string>> outputDigests = new(StringComparer.Ordinal);
    private readonly string root;
    private readonly Dictionary<ProjectGraphNode, string> fingerprints = [];
    internal Dictionary<string, ProjectGraphNode> Nodes
    {
        get;
    }
    internal Dictionary<ProjectGraphNode, string> Directories { get; } = [];
    internal Dictionary<ProjectGraphNode, HashSet<string>> Products { get; } = [];
    internal HashSet<string> Sources
    {
        get;
    }
    internal HashSet<ProjectGraphNode> Eligible { get; } = [];

    internal QualificationInputs(ProjectGraph graph, string root, string sdk,
        IReadOnlyDictionary<string, string> digests, Func<ProjectGraphNode, IEnumerable<string>> inputs,
        Func<ProjectGraphNode, IEnumerable<string>> products, Func<ProjectGraphNode, string> configuration, IEnumerable<string> packages)
    {
        this.root = root;
        Sources = digests.Keys.ToHashSet(StringComparer.Ordinal);
        Nodes = graph.ProjectNodes.ToDictionary(node => Key(node.ProjectInstance));
        using var context = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        Add(context, "qualification-project-v1");
        Add(context, System.Runtime.InteropServices.RuntimeInformation.RuntimeIdentifier);
        Add(context, Math.Clamp(Environment.ProcessorCount, 1, 4).ToString(System.Globalization.CultureInfo.InvariantCulture));
        foreach (var file in new[] { "/etc/os-release", "/usr/bin/bwrap", "/bin/sh" })
        {
            Add(context, file);
            Add(context, SnapshotPayloads.Digest(file));
            Add(context, Mode(file));
        }
        foreach (var (path, digest) in digests.Where(pair => pair.Key.StartsWith(".graph-tools/", StringComparison.Ordinal)).OrderBy(pair => pair.Key, StringComparer.Ordinal))
        {
            Add(context, path);
            Add(context, digest);
        }
        Add(context, SnapshotPayloads.Digest(typeof(QualificationInputs).Assembly.Location));
        foreach (var file in Directory.EnumerateFiles(sdk, "*", SearchOption.AllDirectories).Order(StringComparer.Ordinal))
        {
            Add(context, Path.GetRelativePath(sdk, file));
            Add(context, SnapshotPayloads.Digest(file));
            Add(context, Mode(file));
        }
        foreach (var package in packages.Order(StringComparer.Ordinal))
        {
            Add(context, package);
        }
        var common = Convert.ToHexString(context.GetHashAndReset());
        var own = new Dictionary<ProjectGraphNode, string>();
        foreach (var node in graph.ProjectNodes)
        {
            using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            Add(hash, common);
            Add(hash, Relative(node.ProjectInstance.FullPath));
            Add(hash, configuration(node));
            foreach (var (name, value) in node.ProjectInstance.GlobalProperties.OrderBy(pair => pair.Key, StringComparer.Ordinal))
            {
                Add(hash, name);
                Add(hash, value);
            }
            foreach (var path in inputs(node).Distinct().Order(StringComparer.Ordinal))
            {
                Add(hash, path);
                Add(hash, digests[path]);
            }
            // Restore runs afresh at stable private paths. Include its exact assets
            // and generated imports as well as all declared diagnostic inputs.
            var project = node.ProjectInstance;
            var extensions = project.GetPropertyValue("MSBuildProjectExtensionsPath");
            var assets = project.GetPropertyValue("ProjectAssetsFile");
            if (extensions.Length != 0 && assets.Length != 0)
            {
                var generated = new[] { Full(project, assets),
                    Path.Combine(Full(project, extensions), Path.GetFileName(project.FullPath) + ".nuget.g.props"),
                    Path.Combine(Full(project, extensions), Path.GetFileName(project.FullPath) + ".nuget.g.targets") };
                foreach (var path in generated.Order(StringComparer.Ordinal))
                {
                    Add(hash, Relative(path));
                    Add(hash, File.ReadAllText(path));
                }
            }
            own[node] = Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
            Products[node] = products(node).Select(Relative).ToHashSet(StringComparer.Ordinal);
            var output = project.GetPropertyValue("OutputPath");
            if (GraphProjectKind.HasAssembly(project) && output.Length != 0)
            {
                Directories[node] = Relative(Path.TrimEndingDirectorySeparator(Full(project, output)));
                Eligible.Add(node);
            }
        }
        // Shared output roots/products cannot be independently replayed. Nor
        // can their consumers safely hash an output while another owner writes it.
        var ambiguous = new HashSet<ProjectGraphNode>();
        foreach (var node in graph.ProjectNodes)
        {
            if (graph.ProjectNodes.Any(other => other != node &&
                (Products[node].Overlaps(Products[other]) ||
                 Directories.TryGetValue(node, out var left) && (Products[other].Any(path => path.StartsWith(left + "/", StringComparison.Ordinal)) ||
                    Directories.TryGetValue(other, out var right) && Overlaps(left, right)))))
            {
                ambiguous.Add(node);
            }
        }
        var unsafeDependencies = new Dictionary<ProjectGraphNode, bool>();
        bool Unsafe(ProjectGraphNode node)
        {
            if (!unsafeDependencies.TryGetValue(node, out var value))
            {
                unsafeDependencies[node] = value = ambiguous.Contains(node) || node.ProjectReferences.Any(Unsafe);
            }
            return value;
        }
        Eligible.RemoveWhere(Unsafe);
        foreach (var node in graph.ProjectNodes)
        {
            Compute(node);
        }
        return;

        string Compute(ProjectGraphNode node)
        {
            if (fingerprints.TryGetValue(node, out var existing))
            {
                return existing;
            }
            using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
            Add(hash, own[node]);
            foreach (var dependency in node.ProjectReferences.OrderBy(child => Key(child.ProjectInstance), StringComparer.Ordinal))
            {
                Add(hash, Compute(dependency));
            }
            return fingerprints[node] = Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
        }
    }

    internal string Fingerprint(ProjectGraphNode node, IEnumerable<string> targets)
    {
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        Add(hash, fingerprints[node]);
        foreach (var target in targets)
        {
            Add(hash, target);
        }
        // An uncached producer may emit different bytes for the
        // same source inputs. Include its actual products after MSBuild schedules it.
        foreach (var dependency in node.ProjectReferences.OrderBy(child => Key(child.ProjectInstance), StringComparer.Ordinal))
        {
            Add(hash, fingerprints[dependency]);
            foreach (var path in Files(dependency).Order(StringComparer.Ordinal))
            {
                Add(hash, Relative(path));
                var digest = outputDigests.GetOrAdd(path, file => new Lazy<string>(() => SnapshotPayloads.Digest(file))).Value;
                Add(hash, digest);
                Add(hash, Mode(path));
            }
        }
        var fingerprint = Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
        return fingerprint;
    }
    internal IEnumerable<string> Files(ProjectGraphNode node)
    {
        var files = Products[node].Select(Resolve).Where(File.Exists);
        if (Directories.TryGetValue(node, out var directory) && Directory.Exists(Resolve(directory)))
        {
            files = files.Concat(Tree(Resolve(directory)));
        }
        return files.Distinct(StringComparer.Ordinal);
    }
    private static IEnumerable<string> Tree(string directory)
    {
        foreach (var path in Directory.EnumerateFileSystemEntries(directory))
        {
            if (new FileInfo(path).LinkTarget is not null)
            {
                throw new InvalidDataException("Qualification output symlink: " + path);
            }
            if (Directory.Exists(path))
            {
                foreach (var file in Tree(path))
                {
                    yield return file;
                }
            }
            else
            {
                yield return path;
            }
        }
    }
    internal string Relative(string path) => WorkspaceView.Safe(Path.GetRelativePath(root, path).Replace('\\', '/'));
    internal string Resolve(string path)
    {
        var target = Path.Combine(root, WorkspaceView.Safe(path));
        for (var current = target; current.Length >= root.Length; current = Path.GetDirectoryName(current)!)
        {
            if (new FileInfo(current).LinkTarget is not null)
            {
                throw new InvalidDataException("Qualification artifact symlink: " + current);
            }
            if (current == root)
            {
                break;
            }
        }
        return target;
    }
    internal bool Owns(ProjectGraphNode node, string path) => !Sources.Contains(path) && Eligible.Contains(node) &&
        (path.StartsWith(Directories[node] + "/", StringComparison.Ordinal) || Products[node].Contains(path));
    internal static string Key(ProjectInstance project) => project.FullPath + "|" + string.Join(";", project.GlobalProperties.OrderBy(pair => pair.Key, StringComparer.Ordinal).Select(pair => pair.Key + "=" + pair.Value));
    internal static string Full(ProjectInstance project, string value) => Path.GetFullPath(value.Replace('\\', '/'), Path.GetDirectoryName(project.FullPath)!);
    internal static bool Overlaps(string left, string right) => left == right || left.StartsWith(right + "/", StringComparison.Ordinal) || right.StartsWith(left + "/", StringComparison.Ordinal);
    private static string Mode(string path) => (OperatingSystem.IsWindows() ? 0 : (int)File.GetUnixFileMode(path) & 511)
        .ToString(System.Globalization.CultureInfo.InvariantCulture);
    private static void Add(IncrementalHash hash, string value)
    {
        var bytes = Encoding.UTF8.GetBytes(value);
        hash.AppendData(BitConverter.GetBytes(bytes.Length));
        hash.AppendData(bytes);
    }
}
