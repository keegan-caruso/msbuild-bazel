using System.Collections.Concurrent;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Build.Evaluation;
using Microsoft.Build.Execution;
using Microsoft.Build.Framework;
using Microsoft.Build.Graph;
using Microsoft.Build.ProjectCache;
using RulesMSBuild.ProjectCache;

if (args.Length is < 5 or > 6 || (args.Length == 6 && args[5] is not ("orchard" or "runtime")))
{
    Console.Error.WriteLine("Usage: AvaloniaProbe ROOT ENTRY_RELATIVE READ_CACHE|- WRITE_CACHE REPORT [orchard|runtime]");
    return 2;
}

var root = args[0];
var entry = args[1];
var readCache = args[2];
var writeCache = args[3];
var remoteUrl = Environment.GetEnvironmentVariable("RULES_MSBUILD_PROJECT_CACHE_URL");
using var remote = remoteUrl is null ? null : new RemoteSnapshotStore(new Uri(remoteUrl.TrimEnd('/') + "/"));
var remoteRoot = Path.GetFullPath(writeCache) + ".remote-inputs";
var reportPath = args[4];
var orchard = args.Length == 6 && args[5] == "orchard";
var runtime = args.Length == 6 && args[5] == "runtime";
root = Path.GetFullPath(root);
var timer = Stopwatch.StartNew();
var sdk = Path.Combine(Environment.GetEnvironmentVariable("DOTNET_ROOT") ?? throw new InvalidOperationException("DOTNET_ROOT is required"), "sdk", "10.0.400");
System.Runtime.Loader.AssemblyLoadContext.Default.Resolving += (context, name) =>
    File.Exists(Path.Combine(sdk, name.Name + ".dll")) ? context.LoadFromAssemblyPath(Path.Combine(sdk, name.Name + ".dll")) : null;
Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(sdk, "MSBuild.dll"));
Environment.SetEnvironmentVariable("MSBuildSDKsPath", Path.Combine(sdk, "Sdks"));
var packages = Environment.GetEnvironmentVariable("NUGET_PACKAGES") ?? throw new InvalidOperationException("NUGET_PACKAGES is required");
var properties = new Dictionary<string, string>
{
    ["Configuration"] = "Release",
    ["TargetFramework"] = orchard || runtime ? "net10.0" : "net8.0",
    ["NuGetAudit"] = "false",
    ["RestorePackagesPath"] = packages,
    ["DebugType"] = "portable",
};
if (!runtime)
{
    properties["ProduceReferenceAssembly"] = "true";
    properties["PathMap"] = root + "=/_/workspace";
    if (!orchard)
    {
        properties["AvsSkipBuildingLegacyTargetFrameworks"] = "True";
    }
}
else
{
    properties["TargetArchitecture"] = "arm64";
    properties["TargetOS"] = "osx";
    properties["UseLocalTargetingRuntimePack"] = "false";
    properties["RestoreUseStaticGraphEvaluation"] = "false";
    properties["UseSharedCompilation"] = "false";
    properties["NetCoreSdkRoot"] = sdk;
}
using var collection = new ProjectCollection();
var graph = new ProjectGraph(new ProjectGraphEntryPoint(Path.Combine(root, entry), properties), collection);
var graphSeconds = timer.Elapsed.TotalSeconds;
var targetsByNode = graph.GetTargetLists(["Build"]);
var plugin = new AvaloniaCache(root, packages, readCache == "-" ? null : Path.GetFullPath(readCache), remote, remoteRoot, orchard, runtime);
var targetTimings = new TargetTimingLogger();
var consoleLogger = new Microsoft.Build.Logging.ConsoleLogger(LoggerVerbosity.Minimal);
var parameters = new BuildParameters(collection)
{
    MaxNodeCount = 4,
    EnableNodeReuse = false,
    ProjectCacheDescriptor = ProjectCacheDescriptor.FromInstance(plugin),
    Loggers = Environment.GetEnvironmentVariable("AVALONIA_TARGET_TIMINGS") == "1"
        ? [consoleLogger, targetTimings] : [consoleLogger],
};
bool success;
var buildTimer = Stopwatch.StartNew();
using (var manager = new BuildManager())
{
    var result = manager.Build(parameters, new GraphBuildRequestData(graph, ["Build"]));
    success = result.OverallResult == BuildResultCode.Success;
}
var buildSeconds = buildTimer.Elapsed.TotalSeconds;
var snapshotSeconds = 0.0;
if (success)
{
    var phaseTimer = Stopwatch.StartNew();
    plugin.Save(graph, Path.GetFullPath(writeCache));
    if (remote is not null)
    {
        await plugin.PublishAsync(graph, Path.GetFullPath(writeCache));
        if (Directory.Exists(remoteRoot))
        {
            Directory.Delete(remoteRoot, recursive: true);
        }
    }
    snapshotSeconds = phaseTimer.Elapsed.TotalSeconds;
}
var report = new
{
    graphNodes = graph.ProjectNodes.Count,
    hits = plugin.Hits,
    misses = plugin.Misses,
    graphSeconds,
    buildSeconds,
    snapshotSeconds,
    packageDigestSeconds = AvaloniaCache.Seconds(plugin.PackageDigestTicks),
    sharedDigestSeconds = AvaloniaCache.Seconds(plugin.SharedDigestTicks),
    fingerprintAggregateSeconds = AvaloniaCache.Seconds(plugin.FingerprintTicks),
    cacheLookupAggregateSeconds = AvaloniaCache.Seconds(plugin.CacheLookupTicks),
    cacheRestoreAggregateSeconds = AvaloniaCache.Seconds(plugin.CacheRestoreTicks),
    reusedSnapshotFiles = plugin.ReusedSnapshotFiles,
    linkedSnapshotFiles = plugin.LinkedSnapshotFiles,
    reusedSnapshotBytes = plugin.ReusedSnapshotBytes,
    remoteHits = plugin.RemoteHits,
    remotePublished = plugin.RemotePublished,
    targetTimings = targetTimings.Results(),
    taskTimings = targetTimings.TaskResults(),
    totalSeconds = timer.Elapsed.TotalSeconds,
    success,
    nodes = graph.ProjectNodes.Select(node => new
    {
        project = Path.GetRelativePath(root, node.ProjectInstance.FullPath),
        framework = node.ProjectInstance.GetPropertyValue("TargetFramework"),
        targets = targetsByNode.TryGetValue(node, out var targets) ? targets.ToArray() : [],
        references = node.ProjectReferences.Select(reference => new
        {
            project = Path.GetRelativePath(root, reference.ProjectInstance.FullPath),
            framework = reference.ProjectInstance.GetPropertyValue("TargetFramework"),
        }).OrderBy(reference => reference.project).ThenBy(reference => reference.framework).ToArray(),
    }).OrderBy(node => node.project).ToArray(),
};
Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(reportPath))!);
File.WriteAllText(reportPath, JsonSerializer.Serialize(report, new JsonSerializerOptions { WriteIndented = true }));
Console.WriteLine($"graphNodes={report.graphNodes} hits={report.hits} misses={report.misses} success={report.success}");
return report.success ? 0 : 1;

internal sealed record CacheSnapshot(
    string Fingerprint,
    Dictionary<string, string> Files,
    Dictionary<string, string> ProjectCopies);

internal sealed class TargetTimingLogger : ILogger
{
    private readonly ConcurrentDictionary<(int Node, int Project, int Target), long> started = new();
    private readonly ConcurrentDictionary<string, Counter> totals = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<(int Node, int Project, int Target, int Task), long> taskStarted = new();
    private readonly ConcurrentDictionary<string, Counter> taskTotals = new(StringComparer.Ordinal);

    public LoggerVerbosity Verbosity { get; set; } = LoggerVerbosity.Diagnostic;
    public string? Parameters { get; set; }

    public void Initialize(IEventSource eventSource)
    {
        eventSource.TargetStarted += (_, args) =>
        {
            if (args.BuildEventContext is { } context)
            {
                started[(context.NodeId, context.ProjectContextId, context.TargetId)] = Stopwatch.GetTimestamp();
            }
        };
        eventSource.TargetFinished += (_, args) =>
        {
            if (args.BuildEventContext is { } context &&
                started.TryRemove((context.NodeId, context.ProjectContextId, context.TargetId), out var start))
            {
                var counter = totals.GetOrAdd(args.TargetName, _ => new Counter());
                Interlocked.Add(ref counter.Ticks, Stopwatch.GetTimestamp() - start);
                Interlocked.Increment(ref counter.Count);
            }
        };
        eventSource.TaskStarted += (_, args) =>
        {
            if (args.BuildEventContext is { } context)
            {
                taskStarted[(context.NodeId, context.ProjectContextId, context.TargetId, context.TaskId)] = Stopwatch.GetTimestamp();
            }
        };
        eventSource.TaskFinished += (_, args) =>
        {
            if (args.BuildEventContext is { } context &&
                taskStarted.TryRemove((context.NodeId, context.ProjectContextId, context.TargetId, context.TaskId), out var start))
            {
                var counter = taskTotals.GetOrAdd(args.TaskName, _ => new Counter());
                Interlocked.Add(ref counter.Ticks, Stopwatch.GetTimestamp() - start);
                Interlocked.Increment(ref counter.Count);
            }
        };
    }

    public void Shutdown() { }

    internal Dictionary<string, object> Results() => totals.OrderByDescending(pair => pair.Value.Ticks)
        .ToDictionary(pair => pair.Key, pair => (object)new
        {
            count = pair.Value.Count,
            aggregateSeconds = AvaloniaCache.Seconds(pair.Value.Ticks),
        }, StringComparer.Ordinal);

    internal Dictionary<string, object> TaskResults() => taskTotals.OrderByDescending(pair => pair.Value.Ticks)
        .ToDictionary(pair => pair.Key, pair => (object)new
        {
            count = pair.Value.Count,
            aggregateSeconds = AvaloniaCache.Seconds(pair.Value.Ticks),
        }, StringComparer.Ordinal);

    private sealed class Counter
    {
        internal long Ticks;
        internal int Count;
    }
}

internal sealed class AvaloniaCache(string root, string packages, string? readCache, RemoteSnapshotStore? remote, string remoteRoot, bool orchard, bool runtime) : ProjectCachePluginBase
{
    private Dictionary<string, ProjectGraphNode> nodes = new(StringComparer.Ordinal);
    private Dictionary<string, List<string>> producerOutputs = new(StringComparer.Ordinal);
    private Dictionary<string, HashSet<string>> dependencyOutputs = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, string> fingerprints = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, CacheSnapshot> cacheHits = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, byte> remoteHitFingerprints = new(StringComparer.Ordinal);
    private string packageDigest = "";
    private Dictionary<string, string> sharedDigests = new(StringComparer.Ordinal);
    internal int Hits;
    internal int Misses;
    internal long PackageDigestTicks;
    internal long SharedDigestTicks;
    internal long FingerprintTicks;
    internal long CacheLookupTicks;
    internal long CacheRestoreTicks;
    internal long ReusedSnapshotFiles;
    internal long LinkedSnapshotFiles;
    internal long ReusedSnapshotBytes;
    internal int RemoteHits;
    internal int RemotePublished;

    internal static double Seconds(long ticks) => ticks / (double)Stopwatch.Frequency;

    public override Task BeginBuildAsync(CacheContext context, PluginLoggerBase logger, CancellationToken cancellationToken)
    {
        nodes = context.Graph?.ProjectNodes.ToDictionary(Key, StringComparer.Ordinal)
            ?? throw new InvalidOperationException("The probe requires a static project graph");
        producerOutputs = nodes.Values
            .Where(node => node.ProjectInstance.GetPropertyValue("TargetFramework").Length != 0)
            .SelectMany(node => runtime ? CompanionFiles(TargetFile(node)) :
                new[] { ".dll", ".pdb", ".xml" }.Select(extension =>
                    Path.Combine(Path.GetDirectoryName(node.ProjectInstance.FullPath)!, "bin", "Release",
                        node.ProjectInstance.GetPropertyValue("TargetFramework"),
                        node.ProjectInstance.GetPropertyValue("AssemblyName") + extension)))
            .GroupBy(Path.GetFileName, StringComparer.Ordinal)
            .ToDictionary(group => group.Key!, group => group.ToList(), StringComparer.Ordinal);
        dependencyOutputs = nodes.Values.ToDictionary(Key, DependencyOutputPaths, StringComparer.Ordinal);
        var started = Stopwatch.GetTimestamp();
        packageDigest = DigestSet(Directory.GetFiles(packages, "*.nupkg", SearchOption.AllDirectories), packages);
        PackageDigestTicks = Stopwatch.GetTimestamp() - started;
        started = Stopwatch.GetTimestamp();
        // The shared source tree is immutable during this graph build.
        sharedDigests = SharedPaths().Distinct(StringComparer.Ordinal)
            .ToDictionary(path => path, Digest, StringComparer.Ordinal);
        SharedDigestTicks = Stopwatch.GetTimestamp() - started;
        return Task.CompletedTask;
    }

    public override async Task<CacheResult> GetCacheResultAsync(BuildRequestData request, PluginLoggerBase logger, CancellationToken cancellationToken)
    {
        var key = Key(request.ProjectFullPath, request.GlobalProperties);
        var node = nodes[key];
        var framework = node.ProjectInstance.GetPropertyValue("TargetFramework");
        var started = Stopwatch.GetTimestamp();
        var fingerprint = framework.Length == 0 ? "" : Fingerprint(node);
        Interlocked.Add(ref FingerprintTicks, Stopwatch.GetTimestamp() - started);
        fingerprints[key] = fingerprint;
        started = Stopwatch.GetTimestamp();
        if (framework.Length != 0 && (readCache is not null || remote is not null))
        {
            var source = SnapshotDirectory(readCache ?? remoteRoot, node);
            var fetchedRemotely = readCache is null && remote is not null &&
                await remote.FetchAsync(fingerprint, source, cancellationToken);
            var manifest = Path.Combine(source, "manifest.json");
            if (File.Exists(manifest))
            {
                var snapshot = JsonSerializer.Deserialize<CacheSnapshot>(File.ReadAllText(manifest))!;
                var inputsMatch = snapshot.Fingerprint == fingerprint;
                var pathsAllowed = snapshot.Files.Keys.All(relative => AllowedOutput(node, relative));
                var ownAssemblyPresent = snapshot.Files.ContainsKey(OwnAssembly(node));
                var projectCopiesAllowed = snapshot.ProjectCopies is not null && snapshot.ProjectCopies.All(copy =>
                    AllowedOutput(node, copy.Key) && !snapshot.Files.ContainsKey(copy.Key) &&
                    producerOutputs.TryGetValue(Path.GetFileName(copy.Key), out var candidates) &&
                    candidates.Contains(Path.Combine(root, copy.Value), StringComparer.Ordinal) &&
                    dependencyOutputs[key].Contains(Path.Combine(root, copy.Value)) &&
                    File.Exists(Path.Combine(root, copy.Value)));
                var filesMatch = inputsMatch && pathsAllowed && ownAssemblyPresent && projectCopiesAllowed &&
                    snapshot.Files.All(file => File.Exists(Path.Combine(source, file.Key)) &&
                        Digest(Path.Combine(source, file.Key)) == file.Value);
                if (inputsMatch && pathsAllowed && ownAssemblyPresent && filesMatch && projectCopiesAllowed)
                {
                    var restoreStarted = Stopwatch.GetTimestamp();
                    foreach (var relative in snapshot.Files.Keys)
                    {
                        var target = Path.Combine(SnapshotBase(node), relative);
                        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                        File.Copy(Path.Combine(source, relative), target, true);
                    }
                    foreach (var (relative, producer) in snapshot.ProjectCopies!)
                    {
                        var target = Path.Combine(SnapshotBase(node), relative);
                        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                        LinkOrCopy(Path.Combine(root, producer), target);
                    }
                    Interlocked.Add(ref CacheRestoreTicks, Stopwatch.GetTimestamp() - restoreStarted);
                    cacheHits[key] = snapshot;
                    Interlocked.Increment(ref Hits);
                    if (fetchedRemotely)
                    {
                        Interlocked.Increment(ref RemoteHits);
                        remoteHitFingerprints.TryAdd(fingerprint, 0);
                    }
                    Console.WriteLine("cacheHit=" + Display(node));
                    Interlocked.Add(ref CacheLookupTicks, Stopwatch.GetTimestamp() - started);
                    return CacheResult.IndicateCacheHit(new ProxyTargets(new Dictionary<string, string> { ["GetTargetPath"] = "Build" }));
                }
                Console.WriteLine($"cacheRejected={Display(node)} inputs={inputsMatch} paths={pathsAllowed} assembly={ownAssemblyPresent} files={filesMatch} projectCopies={projectCopiesAllowed}");
            }
        }
        Interlocked.Increment(ref Misses);
        Console.WriteLine("cacheMiss=" + Display(node));
        Interlocked.Add(ref CacheLookupTicks, Stopwatch.GetTimestamp() - started);
        return CacheResult.IndicateNonCacheHit(CacheResultType.CacheMiss);
    }

    public override Task EndBuildAsync(PluginLoggerBase logger, CancellationToken cancellationToken) => Task.CompletedTask;

    internal void Save(ProjectGraph graph, string destination)
    {
        foreach (var node in graph.ProjectNodes)
        {
            if (node.ProjectInstance.GetPropertyValue("TargetFramework").Length == 0)
            {
                continue;
            }
            var source = SnapshotBase(node);
            var target = SnapshotDirectory(destination, node);
            Directory.CreateDirectory(target);
            if ((readCache is not null || remote is not null) && cacheHits.TryGetValue(Key(node), out var hit))
            {
                // A hit did not build this project; only its producer-linked copies can change.
                foreach (var relative in hit.Files.Keys)
                {
                    var output = Path.Combine(target, relative);
                    Directory.CreateDirectory(Path.GetDirectoryName(output)!);
                    if (LinkOrCopy(Path.Combine(SnapshotDirectory(readCache ?? remoteRoot, node), relative), output))
                    {
                        LinkedSnapshotFiles++;
                    }
                    ReusedSnapshotFiles++;
                    ReusedSnapshotBytes += new FileInfo(output).Length;
                }
                File.WriteAllText(Path.Combine(target, "manifest.json"),
                    JsonSerializer.Serialize(new CacheSnapshot(fingerprints[Key(node)], hit.Files, hit.ProjectCopies)));
                continue;
            }
            var files = new Dictionary<string, string>(StringComparer.Ordinal);
            var projectCopies = new Dictionary<string, string>(StringComparer.Ordinal);
            var producerDigests = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var relative in OutputPaths(node))
            {
                var path = Path.Combine(source, relative);
                if (!File.Exists(path))
                {
                    continue;
                }
                var digest = Digest(path);
                if (relative != OwnAssembly(node) &&
                    producerOutputs.TryGetValue(Path.GetFileName(relative), out var candidates))
                {
                    var producer = candidates.FirstOrDefault(candidate =>
                        dependencyOutputs[Key(node)].Contains(candidate) &&
                        File.Exists(candidate) &&
                        (producerDigests.TryGetValue(candidate, out var known) ? known :
                            producerDigests[candidate] = Digest(candidate)) == digest);
                    if (producer is not null)
                    {
                        projectCopies[relative] = Path.GetRelativePath(root, producer);
                        continue;
                    }
                }
                var output = Path.Combine(target, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(output)!);
                File.Copy(path, output, true);
                files[relative] = digest;
            }
            if (!files.ContainsKey(OwnAssembly(node)))
            {
                throw new InvalidDataException("Missing project assembly: " + Display(node));
            }
            File.WriteAllText(Path.Combine(target, "manifest.json"), JsonSerializer.Serialize(new CacheSnapshot(fingerprints[Key(node)], files, projectCopies)));
        }
    }

    internal async Task PublishAsync(ProjectGraph graph, string destination)
    {
        foreach (var node in graph.ProjectNodes)
        {
            if (node.ProjectInstance.GetPropertyValue("TargetFramework").Length == 0)
            {
                continue;
            }
            var key = Key(node);
            var fingerprint = fingerprints[key];
            if (remoteHitFingerprints.ContainsKey(fingerprint))
            {
                continue;
            }
            if (await remote!.PublishAsync(fingerprint, SnapshotDirectory(destination, node), CancellationToken.None))
            {
                RemotePublished++;
            }
        }
    }

    private static bool LinkOrCopy(string source, string target)
    {
        if (File.Exists(target))
        {
            File.Delete(target);
        }
        if (OperatingSystem.IsWindows() || CreateUnixHardLink(source, target) != 0)
        {
            File.Copy(source, target);
            return false;
        }
        return true;
    }

    [DllImport("libc", EntryPoint = "link", SetLastError = true)]
    private static extern int CreateUnixHardLink(string source, string target);

    private HashSet<string> DependencyOutputPaths(ProjectGraphNode node)
    {
        var outputs = new HashSet<string>(StringComparer.Ordinal);
        var visited = new HashSet<ProjectGraphNode>();
        var pending = new Stack<ProjectGraphNode>(node.ProjectReferences);
        while (pending.TryPop(out var dependency))
        {
            if (!visited.Add(dependency))
            {
                continue;
            }
            var project = dependency.ProjectInstance;
            var framework = project.GetPropertyValue("TargetFramework");
            if (framework.Length != 0)
            {
                foreach (var output in runtime ? CompanionFiles(TargetFile(dependency)) :
                    new[] { ".dll", ".pdb", ".xml" }.Select(extension =>
                        Path.Combine(Path.GetDirectoryName(project.FullPath)!, "bin", "Release", framework,
                            project.GetPropertyValue("AssemblyName") + extension)))
                {
                    outputs.Add(output);
                }
            }
            foreach (var reference in dependency.ProjectReferences)
            {
                pending.Push(reference);
            }
        }
        return outputs;
    }

    private string Fingerprint(ProjectGraphNode node)
    {
        var project = node.ProjectInstance;
        var directory = Path.GetDirectoryName(project.FullPath)!;
        var local = Directory.GetFiles(directory, "*", SearchOption.AllDirectories)
            .Where(path => !Path.GetRelativePath(directory, path).Split(Path.DirectorySeparatorChar)
                .Any(part => part is "bin" or "obj"));
        var items = new[] { "Compile", "EmbeddedResource", "Content", "None", "AdditionalFiles", "GlobalAnalyzerConfigFiles", "EditorConfigFiles", "AvaloniaResource", "AvaloniaXaml", "MicroComIdl" }
            .SelectMany(project.GetItems)
            .Select(item => Path.GetFullPath(item.EvaluatedInclude.Replace('\\', '/'), directory))
            .Where(path => path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.Ordinal) &&
                !Path.GetRelativePath(root, path).Split(Path.DirectorySeparatorChar).Any(part => part is "bin" or "obj") && File.Exists(path));
        var assets = Path.Combine(directory, "obj", "project.assets.json");
        var inputs = local.Concat(sharedDigests.Keys).Concat(items).Append(assets)
            .Where(File.Exists).Distinct(StringComparer.Ordinal)
            .Select(path => Path.GetRelativePath(root, path) + ":" +
                (path == assets ? NormalizedAssets(path) : sharedDigests.TryGetValue(path, out var digest) ? digest : Digest(path)));
        var references = node.ProjectReferences.Select(reference =>
        {
            var dependency = reference.ProjectInstance;
            var source = Path.GetDirectoryName(dependency.FullPath)!;
            var framework = dependency.GetPropertyValue("TargetFramework");
            var name = dependency.GetPropertyValue("AssemblyName");
            var authored = project.GetItems("ProjectReference").Where(item =>
                Path.GetFullPath(item.EvaluatedInclude.Replace('\\', '/'), directory) == dependency.FullPath).ToArray();
            var implementation = authored.Any(item =>
                item.GetMetadataValue("OutputItemType").Equals("Analyzer", StringComparison.OrdinalIgnoreCase) ||
                item.GetMetadataValue("ReferenceOutputAssembly").Equals("false", StringComparison.OrdinalIgnoreCase));
            var output = runtime ? TargetFile(reference) : implementation ?
                Path.Combine(source, "bin", "Release", framework, name + ".dll") :
                Path.Combine(source, "obj", "Release", framework, "ref", name + ".dll");
            return Display(reference) + ":" + (File.Exists(output) ? Digest(output) : "MISSING");
        });
        var globals = project.GlobalProperties.OrderBy(pair => pair.Key, StringComparer.Ordinal)
            .Select(pair => pair.Key + "=" + pair.Value.Replace(root, "/_/workspace", StringComparison.Ordinal)
                .Replace(packages, "/_/packages", StringComparison.Ordinal));
        var value = string.Join('\n', inputs.Concat(references).Concat(globals)
            .Order(StringComparer.Ordinal).Prepend("sdk=10.0.400;packages=" + packageDigest));
        return Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(value)));
    }

    private IEnumerable<string> SharedPaths() =>
        new[] { "build", Path.Combine("src", "Shared"), Path.Combine("src", "OrchardCore.Build") }
            .Concat(runtime ? ["eng"] : [])
            .Select(path => Path.Combine(root, path))
            .Where(Directory.Exists)
            .SelectMany(path => Directory.GetFiles(path, "*", SearchOption.AllDirectories))
            .Concat(Directory.GetFiles(root, "*", SearchOption.TopDirectoryOnly))
            .Concat(Directory.GetFiles(root, "*.props", SearchOption.AllDirectories))
            .Concat(Directory.GetFiles(root, "*.targets", SearchOption.AllDirectories))
            .Where(path => !Path.GetRelativePath(root, path).Split(Path.DirectorySeparatorChar)
                .Any(part => part is "bin" or "obj"));

    private IEnumerable<string> OutputPaths(ProjectGraphNode node)
    {
        var project = node.ProjectInstance;
        var directory = Path.GetDirectoryName(project.FullPath)!;
        var framework = project.GetPropertyValue("TargetFramework");
        if (runtime)
        {
            foreach (var folder in RuntimeOutputDirectories(node))
            {
                if (Directory.Exists(folder))
                {
                    foreach (var path in Directory.GetFiles(folder, "*", SearchOption.AllDirectories))
                    {
                        yield return Path.GetRelativePath(root, path);
                    }
                }
            }
            yield break;
        }
        var prefixes = orchard
            ? new[] { Path.Combine("bin", "Release", framework), Path.Combine("obj", "Release", framework) }
            : new[] { Path.Combine("bin", "Release", framework), Path.Combine("obj", "Release", framework, "ref"), Path.Combine("obj", "Release", framework, "refint") };
        foreach (var prefix in prefixes)
        {
            var folder = Path.Combine(directory, prefix);
            if (Directory.Exists(folder))
            {
                foreach (var path in Directory.GetFiles(folder, "*", SearchOption.AllDirectories))
                {
                    yield return Path.GetRelativePath(directory, path);
                }
            }
        }
    }

    private string SnapshotDirectory(string cache, ProjectGraphNode node) =>
        Path.Combine(cache, Path.GetRelativePath(root, node.ProjectInstance.FullPath) + "." + node.ProjectInstance.GetPropertyValue("TargetFramework") + ".cache");

    private string SnapshotBase(ProjectGraphNode node) => runtime ? root : Path.GetDirectoryName(node.ProjectInstance.FullPath)!;

    private string TargetFile(ProjectGraphNode node) => Path.GetFullPath(
        node.ProjectInstance.GetPropertyValue("TargetPath"), Path.GetDirectoryName(node.ProjectInstance.FullPath)!);

    private static IEnumerable<string> CompanionFiles(string target) => new[] { ".dll", ".pdb", ".xml" }
        .Select(extension => Path.ChangeExtension(target, extension));

    private IEnumerable<string> RuntimeOutputDirectories(ProjectGraphNode node) =>
        new[] { "OutputPath", "IntermediateOutputPath" }
            .Select(property => node.ProjectInstance.GetPropertyValue(property))
            .Where(value => value.Length != 0)
            .Select(value => Path.TrimEndingDirectorySeparator(Path.GetFullPath(value,
                Path.GetDirectoryName(node.ProjectInstance.FullPath)!)))
            .Where(path => path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.Ordinal));

    private string OwnAssembly(ProjectGraphNode node) => runtime ? Path.GetRelativePath(root, TargetFile(node)) :
        Path.Combine("bin", "Release", node.ProjectInstance.GetPropertyValue("TargetFramework"), node.ProjectInstance.GetPropertyValue("AssemblyName") + ".dll");

    private bool AllowedOutput(ProjectGraphNode node, string relative)
    {
        if (Path.IsPathRooted(relative) || relative.Split(Path.DirectorySeparatorChar).Contains(".."))
        {
            return false;
        }
        if (runtime)
        {
            return RuntimeOutputDirectories(node).Any(directory =>
                relative.StartsWith(Path.GetRelativePath(root, directory) + Path.DirectorySeparatorChar, StringComparison.Ordinal));
        }
        var framework = node.ProjectInstance.GetPropertyValue("TargetFramework");
        return relative.StartsWith(Path.Combine("bin", "Release", framework) + Path.DirectorySeparatorChar, StringComparison.Ordinal) ||
            (orchard && relative.StartsWith(Path.Combine("obj", "Release", framework) + Path.DirectorySeparatorChar, StringComparison.Ordinal)) ||
            relative.StartsWith(Path.Combine("obj", "Release", framework, "ref") + Path.DirectorySeparatorChar, StringComparison.Ordinal) ||
            relative.StartsWith(Path.Combine("obj", "Release", framework, "refint") + Path.DirectorySeparatorChar, StringComparison.Ordinal);
    }

    private string Display(ProjectGraphNode node) => Path.GetRelativePath(root, node.ProjectInstance.FullPath) + ":" + node.ProjectInstance.GetPropertyValue("TargetFramework");

    private static string Key(ProjectGraphNode node) =>
        node.ProjectInstance.FullPath + "|" + string.Join(";", node.ProjectInstance.GlobalProperties
            .OrderBy(pair => pair.Key, StringComparer.Ordinal).Select(pair => pair.Key + "=" + pair.Value));

    private static string Key(string path, IEnumerable<ProjectPropertyInstance> properties) =>
        path + "|" + string.Join(";", properties.OrderBy(property => property.Name, StringComparer.Ordinal).Select(property => property.Name + "=" + property.EvaluatedValue));

    private static string Digest(string path) => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(path)));

    private string NormalizedAssets(string path)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(path));
        var assets = document.RootElement;
        // Restore records action-local source, home, output and package paths.
        // The resolved assets and framework dependency selection are the inputs
        // to compilation; package archive bytes are fingerprinted separately.
        var value = JsonSerializer.Serialize(new
        {
            targets = assets.GetProperty("targets"),
            libraries = assets.GetProperty("libraries"),
            dependencies = assets.GetProperty("projectFileDependencyGroups"),
            frameworks = assets.GetProperty("project").GetProperty("frameworks"),
        });
        return Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(value)));
    }

    private static string DigestSet(IEnumerable<string> files, string root) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(string.Join('\n', files.Order(StringComparer.Ordinal).Select(path => Path.GetRelativePath(root, path) + ":" + Digest(path))))));
}
