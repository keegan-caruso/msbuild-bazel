using System.Security.Cryptography;
using System.Diagnostics;
using System.Text;
using System.Text.Json;
using Microsoft.Build.Evaluation;
using Microsoft.Build.Execution;
using Microsoft.Build.Graph;
using Microsoft.Build.ProjectCache;

if (args is not [var root, var entry, var readCache, var writeCache])
{
    Console.Error.WriteLine("Usage: CacheProbe ROOT ENTRY_RELATIVE READ_CACHE|- WRITE_CACHE");
    return 2;
}

root = Path.GetFullPath(root);
var timer = Stopwatch.StartNew();
var sdk = Path.Combine(Environment.GetEnvironmentVariable("DOTNET_ROOT") ?? throw new InvalidOperationException("DOTNET_ROOT is required"), "sdk", "10.0.400");
System.Runtime.Loader.AssemblyLoadContext.Default.Resolving += (context, name) =>
    File.Exists(Path.Combine(sdk, name.Name + ".dll")) ? context.LoadFromAssemblyPath(Path.Combine(sdk, name.Name + ".dll")) : null;
Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(sdk, "MSBuild.dll"));
Environment.SetEnvironmentVariable("MSBuildSDKsPath", Path.Combine(sdk, "Sdks"));
var properties = new Dictionary<string, string>
{
    ["Configuration"] = "Release",
    ["DisableTransitiveProjectReferences"] = "true",
    ["Deterministic"] = "true",
    ["PathMap"] = root + "=/_/workspace",
};
using var collection = new ProjectCollection();
var graph = new ProjectGraph(new ProjectGraphEntryPoint(Path.Combine(root, entry), properties), collection);
var graphSeconds = timer.Elapsed.TotalSeconds;
var plugin = new ProbePlugin(root, readCache == "-" ? null : Path.GetFullPath(readCache));
var parameters = new BuildParameters(collection)
{
    MaxNodeCount = 2,
    EnableNodeReuse = false,
    ProjectCacheDescriptor = ProjectCacheDescriptor.FromInstance(plugin),
    Loggers = [new Microsoft.Build.Logging.ConsoleLogger(Microsoft.Build.Framework.LoggerVerbosity.Minimal)],
};
using var manager = new BuildManager();
var result = manager.Build(parameters, new GraphBuildRequestData(graph, ["Build"]));
var buildSeconds = timer.Elapsed.TotalSeconds - graphSeconds;
if (result.OverallResult != BuildResultCode.Success)
{
    Console.WriteLine($"graphNodes={graph.ProjectNodes.Count} hits={plugin.Hits} misses={plugin.Misses} result=Failure");
    return 1;
}

// A cached app assembly must run with today's dependency implementations.
// Project-level snapshots never carry copy-local DLLs from a previous graph.
var entryProject = Path.Combine(root, entry);
var appOutput = Path.Combine(Path.GetDirectoryName(entryProject)!, "bin", "Release", "net10.0");
foreach (var node in graph.ProjectNodes.Where(node => node.ProjectInstance.FullPath != entryProject))
{
    var name = node.ProjectInstance.GetPropertyValue("AssemblyName");
    var implementation = Path.Combine(Path.GetDirectoryName(node.ProjectInstance.FullPath)!, "bin", "Release", "net10.0", name + ".dll");
    if (File.Exists(implementation))
    {
        Directory.CreateDirectory(appOutput);
        File.Copy(implementation, Path.Combine(appOutput, name + ".dll"), true);
    }
}

var output = Path.GetFullPath(writeCache);
Directory.CreateDirectory(output);
foreach (var node in graph.ProjectNodes)
{
    var project = node.ProjectInstance.FullPath;
    var key = Path.GetRelativePath(root, project);
    var destination = Path.Combine(output, key + ".cache");
    Directory.CreateDirectory(destination);
    var files = new Dictionary<string, string>(StringComparer.Ordinal);
    var assembly = node.ProjectInstance.GetPropertyValue("AssemblyName");
    foreach (var relative in ProbePlugin.OwnedOutputs(assembly))
    {
        var source = Path.Combine(Path.GetDirectoryName(project)!, relative);
        if (!File.Exists(source))
        {
            continue;
        }
        var target = Path.Combine(destination, relative);
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        File.Copy(source, target, true);
        files[relative] = ProbePlugin.Digest(source);
    }
    File.WriteAllText(Path.Combine(destination, "manifest.json"), JsonSerializer.Serialize(new Snapshot(ProbePlugin.Fingerprint(node, root), files)));
}
Console.WriteLine($"graphNodes={graph.ProjectNodes.Count} hits={plugin.Hits} misses={plugin.Misses} result=Success");
File.WriteAllText(Path.Combine(output, "report.json"), JsonSerializer.Serialize(new { graphNodes = graph.ProjectNodes.Count, hits = plugin.Hits, misses = plugin.Misses, graphSeconds, buildSeconds, totalSeconds = timer.Elapsed.TotalSeconds }));
return 0;

internal sealed record Snapshot(string Fingerprint, Dictionary<string, string> Files);

internal sealed class ProbePlugin(string root, string? readCache) : ProjectCachePluginBase
{
    private Dictionary<string, ProjectGraphNode> nodes = new(StringComparer.Ordinal);
    internal int Hits;
    internal int Misses;

    public override Task BeginBuildAsync(CacheContext context, PluginLoggerBase logger, CancellationToken cancellationToken)
    {
        nodes = context.Graph?.ProjectNodes.ToDictionary(node => node.ProjectInstance.FullPath, StringComparer.Ordinal)
            ?? throw new InvalidOperationException("The probe requires a static project graph");
        Console.WriteLine($"cacheGraphNodes={nodes.Count}");
        return Task.CompletedTask;
    }

    public override Task<CacheResult> GetCacheResultAsync(BuildRequestData request, PluginLoggerBase logger, CancellationToken cancellationToken)
    {
        var project = request.ProjectFullPath;
        var key = Path.GetRelativePath(root, project);
        if (key.StartsWith("..", StringComparison.Ordinal) || Path.IsPathRooted(key))
        {
            throw new InvalidDataException("Project escaped the synthetic graph root");
        }
        var directory = readCache is null ? null : Path.Combine(readCache, key + ".cache");
        var manifest = directory is null ? null : Path.Combine(directory, "manifest.json");
        if (manifest is not null && File.Exists(manifest))
        {
            var snapshot = JsonSerializer.Deserialize<Snapshot>(File.ReadAllText(manifest))!;
            var assembly = nodes[project].ProjectInstance.GetPropertyValue("AssemblyName");
            var allowed = OwnedOutputs(assembly).ToHashSet(StringComparer.Ordinal);
            if (snapshot.Files.ContainsKey("bin/Release/net10.0/" + assembly + ".dll") &&
                snapshot.Files.Keys.All(allowed.Contains) &&
                snapshot.Fingerprint == Fingerprint(nodes[project], root) && snapshot.Files.All(file =>
                    File.Exists(Path.Combine(directory!, file.Key)) && Digest(Path.Combine(directory!, file.Key)) == file.Value))
            {
                foreach (var (relative, _) in snapshot.Files)
                {
                    var target = Path.Combine(Path.GetDirectoryName(project)!, relative);
                    Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                    File.Copy(Path.Combine(directory!, relative), target, true);
                }
                Interlocked.Increment(ref Hits);
                Console.WriteLine("cacheHit=" + key);
                return Task.FromResult(CacheResult.IndicateCacheHit(new ProxyTargets(new Dictionary<string, string> { ["GetTargetPath"] = "Build" })));
            }
        }
        Interlocked.Increment(ref Misses);
        Console.WriteLine("cacheMiss=" + key);
        return Task.FromResult(CacheResult.IndicateNonCacheHit(CacheResultType.CacheMiss));
    }

    public override Task EndBuildAsync(PluginLoggerBase logger, CancellationToken cancellationToken) => Task.CompletedTask;

    internal static string Fingerprint(ProjectGraphNode node, string root)
    {
        if (node.ProjectInstance.GetItems("PackageReference").Count != 0)
        {
            throw new InvalidDataException("The cache probe only supports package-free projects");
        }
        var project = node.ProjectInstance.FullPath;
        var directory = Path.GetDirectoryName(project)!;
        var sources = Directory.GetFiles(directory, "*.cs", SearchOption.TopDirectoryOnly)
            .Append(project)
            .Append(Path.Combine(root, "global.json"))
            .Select(path => Path.GetRelativePath(root, path) + ":" + Digest(path));
        var references = node.ProjectReferences.Select(reference =>
        {
            var dependency = reference.ProjectInstance;
            var name = dependency.GetPropertyValue("AssemblyName");
            var dir = Path.GetDirectoryName(dependency.FullPath)!;
            var path = Path.Combine(dir, "obj", "Release", "net10.0", "ref", name + ".dll");
            if (!File.Exists(path))
            {
                path = Path.Combine(dir, "bin", "Release", "net10.0", name + ".dll");
            }
            return Path.GetRelativePath(root, dependency.FullPath) + ":" + (File.Exists(path) ? Digest(path) : "MISSING");
        });
        var text = string.Join('\n', sources.Concat(references).Order(StringComparer.Ordinal).Prepend("sdk=10.0.400;configuration=Release"));
        return Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
    }

    internal static string Digest(string path) => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(path)));

    internal static string[] OwnedOutputs(string assembly) => [
        "bin/Release/net10.0/" + assembly + ".dll",
        "bin/Release/net10.0/" + assembly + ".pdb",
        "bin/Release/net10.0/" + assembly + ".deps.json",
        "bin/Release/net10.0/" + assembly + ".runtimeconfig.json",
        "obj/Release/net10.0/ref/" + assembly + ".dll",
        "obj/Release/net10.0/refint/" + assembly + ".dll",
    ];
}
