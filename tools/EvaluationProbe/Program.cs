using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.Build.Definition;
using Microsoft.Build.Evaluation;
using Microsoft.Build.Evaluation.Context;
using Microsoft.Build.Graph;

var options = new JsonSerializerOptions { PropertyNameCaseInsensitive = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true };
if (args is not ["--request", var requestPath]) throw new ArgumentException("usage: EvaluationProbe --request file.json");
var request = JsonSerializer.Deserialize<Request>(File.ReadAllText(requestPath), options) ?? throw new InvalidDataException("empty request");
var sdk = Path.Combine(request.DotnetRoot, "sdk", request.SdkVersion);
System.Runtime.Loader.AssemblyLoadContext.Default.Resolving += (context, name) =>
{
    var candidate = Path.Combine(sdk, name.Name + ".dll");
    return File.Exists(candidate) ? context.LoadFromAssemblyPath(candidate) : null;
};
Environment.SetEnvironmentVariable("DOTNET_ROOT", request.DotnetRoot);
Environment.SetEnvironmentVariable("DOTNET_HOST_PATH", Path.Combine(request.DotnetRoot, "dotnet"));
Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(sdk, "MSBuild.dll"));
Environment.SetEnvironmentVariable("MSBuildSDKsPath", Path.Combine(sdk, "Sdks"));
Environment.SetEnvironmentVariable("NUGET_PACKAGES", Path.Combine(request.Workspace, ".nuget/packages"));
using var collection = new ProjectCollection();
var filesystem = new RecordingFileSystem();
var evaluation = EvaluationContext.Create(EvaluationContext.SharingPolicy.Shared, filesystem);
var rounds = new List<object>();
for (var round = 0; round < (request.Mode == "warm" ? 2 : 1); round++)
{
    filesystem.Observations.Clear();
    var entries = request.EntryPoints.Select(entry => new ProjectGraphEntryPoint(Path.Combine(request.Workspace, entry.Project), entry.GlobalProperties));
    var graph = request.Mode == "plain" ? new ProjectGraph(entries, collection, null) :
        new ProjectGraph(entries, collection, (path, properties, owner) =>
        {
            var project = Project.FromFile(path, new ProjectOptions
            {
                GlobalProperties = properties,
                ProjectCollection = owner,
                EvaluationContext = evaluation,
                LoadSettings = ProjectLoadSettings.RecordEvaluatedItemElements,
            });
            var instance = project.CreateProjectInstance();
            owner.UnloadProject(project);
            return instance;
        });
    var nodes = graph.ProjectNodes.Select(node => new
    {
        Project = node.ProjectInstance.FullPath,
        Properties = node.ProjectInstance.GlobalProperties.OrderBy(p => p.Key, StringComparer.Ordinal).ToDictionary(),
        Values = request.Properties.ToDictionary(name => name, name => node.ProjectInstance.GetPropertyValue(name)),
        Items = request.Items.ToDictionary(name => name, name => node.ProjectInstance.GetItems(name).Select(item => new
        {
            item.EvaluatedInclude,
            Metadata = item.Metadata.OrderBy(m => m.Name, StringComparer.Ordinal).ToDictionary(m => m.Name, m => m.EvaluatedValue),
        }).ToArray()),
        Dependencies = node.ProjectReferences.Select(n => n.ProjectInstance.FullPath).Order(StringComparer.Ordinal).ToArray(),
        Imports = node.ProjectInstance.ImportPaths.Prepend(node.ProjectInstance.FullPath).Distinct().Order(StringComparer.Ordinal)
            .Select(path => new { Path = path, Sha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant() }).ToArray(),
    }).OrderBy(n => n.Project, StringComparer.Ordinal).ThenBy(n => JsonSerializer.Serialize(n.Properties), StringComparer.Ordinal).ToArray();
    rounds.Add(new { Nodes = nodes, Observations = filesystem.Observations.ToArray() });
}
File.WriteAllText(request.Output, JsonSerializer.Serialize(new { SchemaVersion = 1, request.Mode, ReuseEnabled = false, Rounds = rounds }, options) + "\n");

internal sealed record Entry(string Project, Dictionary<string, string> GlobalProperties);
internal sealed record Request(string Workspace, string DotnetRoot, string SdkVersion, Entry[] EntryPoints, string[] Properties, string[] Items, string Mode, string Output);
