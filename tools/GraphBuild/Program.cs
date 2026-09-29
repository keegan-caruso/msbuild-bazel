using System.Text.Json;
using RulesMSBuild.GraphBuild;

if (args is not ["inspect", var root, var contractPath, var report])
{
    Console.Error.WriteLine("Usage: GraphBuild inspect ROOT CONTRACT REPORT");
    return 2;
}
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
File.WriteAllText(report, JsonSerializer.Serialize(inputs.Graph.ProjectNodes.Select(node => new
{
    project = inputs.Relative(node),
    properties = node.ProjectInstance.GlobalProperties,
    fingerprint = inputs.Fingerprint(node),
}), new JsonSerializerOptions { WriteIndented = true }));
return 0;
