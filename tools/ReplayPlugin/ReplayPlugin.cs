using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Build.Execution;
using Microsoft.Build.Framework;
using Microsoft.Build.ProjectCache;
using TaskItem = Microsoft.Build.Utilities.TaskItem;

public sealed record Artifact(string Path, long Size, string Sha256);
public sealed record Item(string Spec, Dictionary<string, string> Metadata);
public sealed record Payload(int SchemaVersion, string SdkVersion, string EngineVersion,
    string Project, string TargetFramework, Dictionary<string, string> RootMappings,
    Dictionary<string, string> Properties, string[] RequestedTargets,
    Dictionary<string, Item[]> Targets);

public sealed class ReplayPlugin : ProjectCachePluginBase
{
    private static readonly JsonSerializerOptions Json = new() { WriteIndented = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    private static readonly Dictionary<string, string> RootMappings = new()
    {
        ["${WORKSPACE}"] = "action-workspace",
        ["${NUGET}"] = "${WORKSPACE}/.nuget/packages",
        ["${SDK}"] = "dotnet-sdk:10.0.400"
    };
    private string workspace = "", bundle = "", mode = "";
    private string? graphProject;
    private string capturedFramework = "net10.0";
    private string[] graphBundles = [];
    private Dictionary<string, string> graphProperties = new(StringComparer.OrdinalIgnoreCase);
    private KeyValuePair<string, string>[] roots = [];
    private static string Engine => FileVersionInfo.GetVersionInfo(typeof(BuildManager).Assembly.Location).FileVersion!;
    private string PayloadPath => Path.Combine(bundle, "results.json");

    public override Task BeginBuildAsync(CacheContext context, PluginLoggerBase logger, CancellationToken token)
    {
        workspace = Environment.GetEnvironmentVariable("RULES_MSBUILD_REPLAY_WORKSPACE")!;
        bundle = Environment.GetEnvironmentVariable("RULES_MSBUILD_REPLAY_BUNDLE")!;
        mode = Environment.GetEnvironmentVariable("RULES_MSBUILD_REPLAY_MODE")!;
        graphProject = Environment.GetEnvironmentVariable("RULES_MSBUILD_GRAPH_PROJECT");
        var dependencies = Environment.GetEnvironmentVariable("RULES_MSBUILD_GRAPH_DEPENDENCIES");
        if (graphProject is not null && dependencies is not null)
            graphBundles = JsonSerializer.Deserialize<string[]>(dependencies)!;
        var configuredProperties = Environment.GetEnvironmentVariable("RULES_MSBUILD_GRAPH_PROPERTIES");
        if (configuredProperties is not null)
        {
            graphProperties = JsonSerializer.Deserialize<Dictionary<string, string>>(configuredProperties)!;
            // -graphBuild injects this global into every request and capture.
            graphProperties["IsGraphBuild"] = "true";
        }
        if (mode is not ("capture" or "replay")) throw new InvalidOperationException("dependency replay mode invalid");
        roots = new Dictionary<string, string>
        {
            ["${NUGET}"] = Path.Combine(workspace, ".nuget/packages"),
            ["${WORKSPACE}"] = workspace,
            ["${SDK}"] = Path.GetDirectoryName(typeof(BuildManager).Assembly.Location)!
        }.OrderByDescending(pair => pair.Value.Length).ToArray();
        if (context.Graph != null)
        {
            if (context.Graph.ProjectNodes.Any(node => node.ProjectInstance.GetPropertyValue("TargetFramework") is not ("net10.0" or "netstandard2.0")))
                throw new InvalidOperationException("dependency framework must be net10.0 or netstandard2.0");
            if (graphProject is not null)
                capturedFramework = context.Graph.ProjectNodes.Single(node =>
                    Path.GetRelativePath(workspace, node.ProjectInstance.FullPath) == graphProject)
                    .ProjectInstance.GetPropertyValue("TargetFramework");
            var targets = context.Graph.GetTargetLists(["Build", "Publish"]);
            File.WriteAllText(Path.Combine(bundle, $"graph-{mode}.json"), JsonSerializer.Serialize(
                targets.Select(pair => new { project = Path.GetRelativePath(workspace, pair.Key.ProjectInstance.FullPath), properties = Properties(pair.Key.ProjectInstance.GlobalProperties), targets = pair.Value }), Json));
        }
        return Task.CompletedTask;
    }

    private string Normalize(string value)
    {
        foreach (var root in roots)
            value = value.Replace(root.Value + "/", root.Key + "/", StringComparison.Ordinal)
                         .Replace(root.Value + "\\", root.Key + "/", StringComparison.Ordinal);
        foreach (var root in roots)
            if (value == root.Value) value = root.Key;
        // This deliberately rejects unfamiliar absolute path forms instead of guessing.
        if (Regex.IsMatch(value, @"(^|[;=\s""'>])/(?!/)|[A-Za-z]:[\\/]|^\\\\"))
            throw new InvalidOperationException($"dependency unsupported external path: {value}");
        return value;
    }

    private string Expand(string value)
    {
        // Validate the normalized form before substituting the consumer roots.
        if (Normalize(value) != value) throw new InvalidOperationException("dependency unnormalized path");
        foreach (var root in roots) value = value.Replace(root.Key, root.Value, StringComparison.Ordinal);
        if (value.Contains("${")) throw new InvalidOperationException("dependency unknown root token");
        return value;
    }

    private Dictionary<string, string> Properties(IEnumerable<KeyValuePair<string, string>> properties) =>
        properties.ToDictionary(pair => pair.Key, pair => Normalize(pair.Value), StringComparer.OrdinalIgnoreCase);

    public override Task<CacheResult> GetCacheResultAsync(BuildRequestData request, PluginLoggerBase logger, CancellationToken token)
    {
        try { return Evaluate(request); }
        catch (Exception error)
        {
            logger.LogError("dependency replay rejected: " + error.Message);
            return Task.FromResult(CacheResult.IndicateNonCacheHit(CacheResultType.None));
        }
    }

    private static bool SameProperties(Dictionary<string, string> left, Dictionary<string, string> right) =>
        left.Count == right.Count && left.All(pair => right.Any(other => string.Equals(pair.Key, other.Key, StringComparison.OrdinalIgnoreCase) && pair.Value == other.Value));

    private Task<CacheResult> Evaluate(BuildRequestData request)
    {
        var project = Path.GetRelativePath(workspace, request.ProjectInstance!.FullPath);
        if (graphProject is not null && project == graphProject && SameProperties(Properties(request.ProjectInstance.GlobalProperties), graphProperties))
            return Task.FromResult(CacheResult.IndicateNonCacheHit(CacheResultType.CacheMiss));
        if (graphProject is null && project != "Shared/Shared.csproj")
            return Task.FromResult(CacheResult.IndicateNonCacheHit(CacheResultType.CacheNotApplicable));
        Console.WriteLine("RULES_MSBUILD_REPLAY_REQUEST:" + string.Join(";", request.TargetNames));
        if (graphProject is null && mode == "capture") return Task.FromResult(CacheResult.IndicateNonCacheHit(CacheResultType.CacheMiss));
        var matches = graphProject is null ? [bundle] : graphBundles.Where(candidate =>
        {
            var data = JsonSerializer.Deserialize<Payload>(File.ReadAllText(Path.Combine(candidate, "results.json")), Json)!;
            return data.Project == project && SameProperties(data.Properties, Properties(request.ProjectInstance.GlobalProperties));
        }).ToArray();
        if (matches.Length == 0 && graphBundles.Any(candidate =>
            JsonSerializer.Deserialize<Payload>(File.ReadAllText(Path.Combine(candidate, "results.json")), Json)!.Project == project))
            throw new InvalidOperationException("dependency global properties mismatch");
        if (matches.Length != 1) throw new InvalidOperationException("dependency configured bundle missing or ambiguous: " + project);
        var dependencyBundle = matches[0];
        var payloadPath = Path.Combine(dependencyBundle, "results.json");
        if (!File.Exists(payloadPath)) throw new InvalidOperationException("dependency payload missing");
        var payload = JsonSerializer.Deserialize<Payload>(File.ReadAllText(payloadPath), Json)!;
        if (payload.SchemaVersion != 1 || payload.SdkVersion != "10.0.400" || payload.EngineVersion != Engine ||
            payload.Project != project || payload.TargetFramework != request.ProjectInstance.GetPropertyValue("TargetFramework")) throw new InvalidOperationException("dependency identity/version mismatch");
        if (payload.RootMappings.Count != RootMappings.Count || RootMappings.Any(pair =>
            !payload.RootMappings.TryGetValue(pair.Key, out var value) || value != pair.Value))
            throw new InvalidOperationException("dependency root mappings mismatch");
        var properties = Properties(request.ProjectInstance.GlobalProperties);
        if (!SameProperties(properties, payload.Properties))
            throw new InvalidOperationException("dependency global properties mismatch");
        foreach (var target in request.TargetNames)
            if (!payload.Targets.ContainsKey(target)) throw new InvalidOperationException("dependency target missing: " + target);
        var artifacts = JsonSerializer.Deserialize<Artifact[]>(File.ReadAllText(Path.Combine(dependencyBundle, "artifacts.json")), Json)!;
        if (artifacts.Length == 0) throw new InvalidOperationException("dependency artifacts empty");
        foreach (var artifact in artifacts)
        {
            if (Path.IsPathRooted(artifact.Path) || artifact.Path.Split('/').Contains("..") ||
                !(artifact.Path.StartsWith(Path.Combine(Path.GetDirectoryName(project)!, "bin") + "/", StringComparison.Ordinal) || artifact.Path.StartsWith(Path.Combine(Path.GetDirectoryName(project)!, "obj") + "/", StringComparison.Ordinal)))
                throw new InvalidOperationException("dependency artifact path invalid");
            var path = Path.Combine(workspace, artifact.Path);
            if (!File.Exists(path) || new FileInfo(path).Length != artifact.Size ||
                Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant() != artifact.Sha256)
                throw new InvalidOperationException("dependency staged artifact missing or corrupt: " + artifact.Path);
        }
        var results = payload.Targets.Select(pair => new PluginTargetResult(pair.Key,
            pair.Value.Select(item =>
            {
                ITaskItem2 result = new TaskItem();
                result.EvaluatedIncludeEscaped = Expand(item.Spec);
                foreach (var metadata in item.Metadata) result.SetMetadata(metadata.Key, Expand(metadata.Value));
                return result;
            }).ToArray(), BuildResultCode.Success)).ToArray();
        Console.WriteLine("RULES_MSBUILD_REPLAY_HIT:" + Path.GetFileNameWithoutExtension(project));
        return Task.FromResult(CacheResult.IndicateCacheHit(results));
    }

    public override Task HandleProjectFinishedAsync(FileAccessContext context, BuildResult result, PluginLoggerBase logger, CancellationToken token)
    {
        if (mode != "capture" || Path.GetRelativePath(workspace, context.ProjectFullPath) != (graphProject ?? "Shared/Shared.csproj") || (graphProject is not null && !SameProperties(Properties(context.GlobalProperties), graphProperties))) return Task.CompletedTask;
        if (result.OverallResult != BuildResultCode.Success) throw new InvalidOperationException("dependency capture failed");
        var targets = result.ResultsByTarget.ToDictionary(pair => pair.Key, pair =>
        {
            if (pair.Value.ResultCode != TargetResultCode.Success) throw new InvalidOperationException("dependency target unsuccessful");
            return pair.Value.Items.Select(item => new Item(Normalize(((ITaskItem2)item).EvaluatedIncludeEscaped),
                ((ITaskItem2)item).CloneCustomMetadataEscaped().Keys.Cast<string>()
                    .ToDictionary(name => name, name => Normalize(((ITaskItem2)item).GetMetadataValueEscaped(name))))).ToArray();
        });
        File.WriteAllText(PayloadPath, JsonSerializer.Serialize(new Payload(1, "10.0.400", Engine,
            graphProject ?? "Shared/Shared.csproj", capturedFramework, RootMappings, Properties(context.GlobalProperties), context.Targets.ToArray(), targets), Json));
        Console.WriteLine("RULES_MSBUILD_REPLAY_CAPTURE:" + string.Join(";", targets.Keys));
        return Task.CompletedTask;
    }
    public override Task EndBuildAsync(PluginLoggerBase logger, CancellationToken token) => Task.CompletedTask;
}
