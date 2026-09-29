using System.Text.Json;
using Microsoft.Build.Execution;
using Microsoft.Build.Graph;
using Microsoft.Build.ProjectCache;
using RulesMSBuild.GraphBuild;

if (args.Length < 4 || args[0] is not ("inspect" or "build"))
{
    Console.Error.WriteLine("Usage: GraphBuild inspect ROOT CONTRACT REPORT | build ROOT CONTRACT REPORT CACHE [TARGET] [no-read]");
    return 2;
}
var root = args[1];
var contractPath = args[2];
var report = args[3];
var cache = args.Length > 4 ? Path.GetFullPath(args[4]) : null;
var contract = JsonSerializer.Deserialize<GraphContract>(File.ReadAllText(contractPath))
    ?? throw new InvalidDataException("Missing graph contract");
report = Path.GetFullPath(report);
Directory.SetCurrentDirectory(root);
root = Directory.GetCurrentDirectory();
var sdkRoot = Environment.GetEnvironmentVariable("DOTNET_ROOT") ?? throw new InvalidDataException("DOTNET_ROOT is required");
var sdk = Path.Combine(sdkRoot, "sdk", contract.SdkVersion);
System.Runtime.Loader.AssemblyLoadContext.Default.Resolving += (context, name) =>
    File.Exists(Path.Combine(sdk, name.Name + ".dll")) ? context.LoadFromAssemblyPath(Path.Combine(sdk, name.Name + ".dll")) : null;
Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(sdk, "MSBuild.dll"));
Environment.SetEnvironmentVariable("MSBuildSDKsPath", Path.Combine(sdk, "Sdks"));
using var inputs = new GraphInputs(contract, root, sdkRoot);
if (args[0] == "build")
{
    var target = args.Length > 5 ? args[5] : "Build";
    if (target is not ("Build" or "Publish"))
    {
        throw new InvalidDataException("The graph runner currently qualifies Build and Publish; execute tests through Bazel test actions");
    }
    foreach (var directory in inputs.Graph.ProjectNodes.SelectMany(inputs.OutputDirectories))
    {
        if (Directory.Exists(directory) && Directory.EnumerateFileSystemEntries(directory).Any())
        {
            throw new InvalidDataException("Graph execution requires empty declared output directories: " + directory);
        }
    }
    var timer = System.Diagnostics.Stopwatch.StartNew();
    var plugin = new GraphCache(inputs, cache ?? throw new InvalidDataException("Cache directory is required"), args.Length < 7 || args[6] != "no-read");
    var parameters = new BuildParameters(inputs.Collection)
    {
        MaxNodeCount = 4,
        EnableNodeReuse = false,
        ProjectCacheDescriptor = ProjectCacheDescriptor.FromInstance(plugin),
        Loggers = [new Microsoft.Build.Logging.ConsoleLogger(Microsoft.Build.Framework.LoggerVerbosity.Minimal)],
    };
    using var manager = new BuildManager();
    var result = manager.Build(parameters, new GraphBuildRequestData(inputs.Graph, [target]));
    if (result.OverallResult != BuildResultCode.Success)
    {
        Console.Error.WriteLine(result.Exception);
        foreach (var pair in result.ResultsByNode)
        {
            Console.Error.WriteLine(pair.Key.ProjectInstance.FullPath + ": " + pair.Value.Exception);
        }
        return 1;
    }
    plugin.Save(result);
    File.WriteAllText(report, JsonSerializer.Serialize(new
    {
        hits = plugin.Hits,
        misses = plugin.Misses,
        seconds = timer.Elapsed.TotalSeconds
    }));
    return 0;
}
File.WriteAllText(report, JsonSerializer.Serialize(inputs.Graph.ProjectNodes.Select(node => new
{
    project = inputs.Relative(node),
    properties = node.ProjectInstance.GlobalProperties,
    fingerprint = inputs.Fingerprint(node),
}), new JsonSerializerOptions { WriteIndented = true }));
return 0;
