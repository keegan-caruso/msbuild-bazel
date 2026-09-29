using System.Collections.Concurrent;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Build.Evaluation;
using Microsoft.Build.Execution;
using Microsoft.Build.Framework;
using Microsoft.Build.Graph;
using Microsoft.Build.ProjectCache;

if (args is not [var root, var entry, var readCache, var writeCache, var reportPath])
{
    Console.Error.WriteLine("Usage: AvaloniaProbe ROOT ENTRY_RELATIVE READ_CACHE|- WRITE_CACHE REPORT");
    return 2;
}

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
    ["TargetFramework"] = "net8.0",
    ["AvsSkipBuildingLegacyTargetFrameworks"] = "True",
    ["NuGetAudit"] = "false",
    ["RestorePackagesPath"] = packages,
    ["DebugType"] = "portable",
    ["ProduceReferenceAssembly"] = "true",
    ["PathMap"] = root + "=/_/workspace",
};
using var collection = new ProjectCollection();
var graph = new ProjectGraph(new ProjectGraphEntryPoint(Path.Combine(root, entry), properties), collection);
var graphSeconds = timer.Elapsed.TotalSeconds;
var targetsByNode = graph.GetTargetLists(["Build"]);
var plugin = new AvaloniaCache(root, packages, readCache == "-" ? null : Path.GetFullPath(readCache));
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
var copyLocalSeconds = 0.0;
var snapshotSeconds = 0.0;
if (success)
{
    var phaseTimer = Stopwatch.StartNew();
    RefreshCopyLocal(graph);
    copyLocalSeconds = phaseTimer.Elapsed.TotalSeconds;
    phaseTimer.Restart();
    plugin.Save(graph, Path.GetFullPath(writeCache));
    snapshotSeconds = phaseTimer.Elapsed.TotalSeconds;
}
var report = new
{
    graphNodes = graph.ProjectNodes.Count,
    hits = plugin.Hits,
    misses = plugin.Misses,
    graphSeconds,
    buildSeconds,
    copyLocalSeconds,
    snapshotSeconds,
    packageDigestSeconds = AvaloniaCache.Seconds(plugin.PackageDigestTicks),
    fingerprintAggregateSeconds = AvaloniaCache.Seconds(plugin.FingerprintTicks),
    cacheLookupAggregateSeconds = AvaloniaCache.Seconds(plugin.CacheLookupTicks),
    cacheRestoreAggregateSeconds = AvaloniaCache.Seconds(plugin.CacheRestoreTicks),
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

static void RefreshCopyLocal(ProjectGraph graph)
{
    var projects = graph.ProjectNodes.Where(node => node.ProjectInstance.GetPropertyValue("TargetFramework").Length != 0).ToArray();
    var assemblies = new Dictionary<(string Framework, string Assembly, string Extension), byte[]>();
    foreach (var producer in projects)
    {
        var framework = producer.ProjectInstance.GetPropertyValue("TargetFramework");
        var directory = Path.Combine(Path.GetDirectoryName(producer.ProjectInstance.FullPath)!, "bin", "Release", framework);
        var name = producer.ProjectInstance.GetPropertyValue("AssemblyName");
        foreach (var extension in new[] { ".dll", ".pdb", ".xml" })
        {
            var path = Path.Combine(directory, name + extension);
            if (File.Exists(path))
            {
                assemblies[(framework, name, extension)] = File.ReadAllBytes(path);
            }
        }
    }
    foreach (var consumer in projects)
    {
        var framework = consumer.ProjectInstance.GetPropertyValue("TargetFramework");
        var directory = Path.Combine(Path.GetDirectoryName(consumer.ProjectInstance.FullPath)!, "bin", "Release", framework);
        if (!Directory.Exists(directory))
        {
            continue;
        }
        foreach (var ((producerFramework, assembly, extension), bytes) in assemblies)
        {
            if (producerFramework != framework || consumer.ProjectInstance.GetPropertyValue("AssemblyName") == assembly)
            {
                continue;
            }
            var name = assembly + extension;
            if (File.Exists(Path.Combine(directory, name)))
            {
                var replacement = Path.Combine(directory, name + ".cache-replacement-" + Guid.NewGuid().ToString("N"));
                try
                {
                    File.WriteAllBytes(replacement, bytes);
                    File.Move(replacement, Path.Combine(directory, name), true);
                }
                finally
                {
                    if (File.Exists(replacement))
                    {
                        File.Delete(replacement);
                    }
                }
            }
        }
    }
}

internal sealed record CacheSnapshot(string Fingerprint, Dictionary<string, string> Files);

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

internal sealed class AvaloniaCache(string root, string packages, string? readCache) : ProjectCachePluginBase
{
    private Dictionary<string, ProjectGraphNode> nodes = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, string> fingerprints = new(StringComparer.Ordinal);
    private string packageDigest = "";
    internal int Hits;
    internal int Misses;
    internal long PackageDigestTicks;
    internal long FingerprintTicks;
    internal long CacheLookupTicks;
    internal long CacheRestoreTicks;

    internal static double Seconds(long ticks) => ticks / (double)Stopwatch.Frequency;

    public override Task BeginBuildAsync(CacheContext context, PluginLoggerBase logger, CancellationToken cancellationToken)
    {
        nodes = context.Graph?.ProjectNodes.ToDictionary(Key, StringComparer.Ordinal)
            ?? throw new InvalidOperationException("The probe requires a static project graph");
        var started = Stopwatch.GetTimestamp();
        packageDigest = DigestSet(Directory.GetFiles(packages, "*.nupkg", SearchOption.AllDirectories), packages);
        PackageDigestTicks = Stopwatch.GetTimestamp() - started;
        return Task.CompletedTask;
    }

    public override Task<CacheResult> GetCacheResultAsync(BuildRequestData request, PluginLoggerBase logger, CancellationToken cancellationToken)
    {
        var key = Key(request.ProjectFullPath, request.GlobalProperties);
        var node = nodes[key];
        var framework = node.ProjectInstance.GetPropertyValue("TargetFramework");
        var started = Stopwatch.GetTimestamp();
        var fingerprint = framework.Length == 0 ? "" : Fingerprint(node);
        Interlocked.Add(ref FingerprintTicks, Stopwatch.GetTimestamp() - started);
        fingerprints[key] = fingerprint;
        started = Stopwatch.GetTimestamp();
        if (framework.Length != 0 && readCache is not null)
        {
            var source = SnapshotDirectory(readCache, node);
            var manifest = Path.Combine(source, "manifest.json");
            if (File.Exists(manifest))
            {
                var snapshot = JsonSerializer.Deserialize<CacheSnapshot>(File.ReadAllText(manifest))!;
                var inputsMatch = snapshot.Fingerprint == fingerprint;
                var pathsAllowed = snapshot.Files.Keys.All(relative => AllowedOutput(node, relative));
                var ownAssemblyPresent = snapshot.Files.ContainsKey(OwnAssembly(node));
                var filesMatch = snapshot.Files.All(file => File.Exists(Path.Combine(source, file.Key)) &&
                    Digest(Path.Combine(source, file.Key)) == file.Value);
                if (inputsMatch && pathsAllowed && ownAssemblyPresent && filesMatch)
                {
                    var restoreStarted = Stopwatch.GetTimestamp();
                    foreach (var relative in snapshot.Files.Keys)
                    {
                        var target = Path.Combine(Path.GetDirectoryName(node.ProjectInstance.FullPath)!, relative);
                        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                        File.Copy(Path.Combine(source, relative), target, true);
                    }
                    Interlocked.Add(ref CacheRestoreTicks, Stopwatch.GetTimestamp() - restoreStarted);
                    Interlocked.Increment(ref Hits);
                    Console.WriteLine("cacheHit=" + Display(node));
                    Interlocked.Add(ref CacheLookupTicks, Stopwatch.GetTimestamp() - started);
                    return Task.FromResult(CacheResult.IndicateCacheHit(new ProxyTargets(new Dictionary<string, string> { ["GetTargetPath"] = "Build" })));
                }
                Console.WriteLine($"cacheRejected={Display(node)} inputs={inputsMatch} paths={pathsAllowed} assembly={ownAssemblyPresent} files={filesMatch}");
            }
        }
        Interlocked.Increment(ref Misses);
        Console.WriteLine("cacheMiss=" + Display(node));
        Interlocked.Add(ref CacheLookupTicks, Stopwatch.GetTimestamp() - started);
        return Task.FromResult(CacheResult.IndicateNonCacheHit(CacheResultType.CacheMiss));
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
            var source = Path.GetDirectoryName(node.ProjectInstance.FullPath)!;
            var target = SnapshotDirectory(destination, node);
            Directory.CreateDirectory(target);
            var files = new Dictionary<string, string>(StringComparer.Ordinal);
            foreach (var relative in OutputPaths(node))
            {
                var path = Path.Combine(source, relative);
                if (!File.Exists(path))
                {
                    continue;
                }
                var output = Path.Combine(target, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(output)!);
                File.Copy(path, output, true);
                files[relative] = Digest(path);
            }
            if (!files.ContainsKey(OwnAssembly(node)))
            {
                throw new InvalidDataException("Missing project assembly: " + Display(node));
            }
            File.WriteAllText(Path.Combine(target, "manifest.json"), JsonSerializer.Serialize(new CacheSnapshot(fingerprints[Key(node)], files)));
        }
    }

    private string Fingerprint(ProjectGraphNode node)
    {
        var project = node.ProjectInstance;
        var directory = Path.GetDirectoryName(project.FullPath)!;
        var local = Directory.GetFiles(directory, "*", SearchOption.AllDirectories)
            .Where(path => !Path.GetRelativePath(directory, path).Split(Path.DirectorySeparatorChar)
                .Any(part => part is "bin" or "obj"));
        var shared = Directory.GetFiles(Path.Combine(root, "build"), "*", SearchOption.AllDirectories)
            .Concat(Directory.GetFiles(Path.Combine(root, "src", "Shared"), "*", SearchOption.AllDirectories))
            .Concat(Directory.GetFiles(root, "*", SearchOption.TopDirectoryOnly))
            .Concat(Directory.GetFiles(root, "*.props", SearchOption.AllDirectories))
            .Concat(Directory.GetFiles(root, "*.targets", SearchOption.AllDirectories))
            .Where(path => !Path.GetRelativePath(root, path).Split(Path.DirectorySeparatorChar)
                .Any(part => part is "bin" or "obj"));
        var items = new[] { "Compile", "EmbeddedResource", "Content", "None", "AdditionalFiles", "GlobalAnalyzerConfigFiles", "EditorConfigFiles", "AvaloniaResource", "AvaloniaXaml", "MicroComIdl" }
            .SelectMany(project.GetItems)
            .Select(item => Path.GetFullPath(item.EvaluatedInclude.Replace('\\', '/'), directory))
            .Where(path => path.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.Ordinal) &&
                !Path.GetRelativePath(root, path).Split(Path.DirectorySeparatorChar).Any(part => part is "bin" or "obj") && File.Exists(path));
        var assets = Path.Combine(directory, "obj", "project.assets.json");
        var inputs = local.Concat(shared).Concat(items).Append(assets)
            .Where(File.Exists).Distinct(StringComparer.Ordinal)
            .Select(path => Path.GetRelativePath(root, path) + ":" +
                (path == assets ? NormalizedAssets(path) : Digest(path)));
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
            var output = implementation ? Path.Combine(source, "bin", "Release", framework, name + ".dll") :
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

    private IEnumerable<string> OutputPaths(ProjectGraphNode node)
    {
        var project = node.ProjectInstance;
        var directory = Path.GetDirectoryName(project.FullPath)!;
        var framework = project.GetPropertyValue("TargetFramework");
        foreach (var prefix in new[] { Path.Combine("bin", "Release", framework), Path.Combine("obj", "Release", framework, "ref"), Path.Combine("obj", "Release", framework, "refint") })
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

    private string OwnAssembly(ProjectGraphNode node) => Path.Combine("bin", "Release", node.ProjectInstance.GetPropertyValue("TargetFramework"), node.ProjectInstance.GetPropertyValue("AssemblyName") + ".dll");

    private static bool AllowedOutput(ProjectGraphNode node, string relative)
    {
        if (Path.IsPathRooted(relative) || relative.Split(Path.DirectorySeparatorChar).Contains(".."))
        {
            return false;
        }
        var framework = node.ProjectInstance.GetPropertyValue("TargetFramework");
        return relative.StartsWith(Path.Combine("bin", "Release", framework) + Path.DirectorySeparatorChar, StringComparison.Ordinal) ||
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
