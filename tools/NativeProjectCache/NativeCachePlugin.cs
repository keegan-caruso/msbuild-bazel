using System.Collections.Concurrent;
using System.Text.Json;
using System.Text.Json.Nodes;
using ActionRunner;
using Microsoft.Build.Execution;
using Microsoft.Build.Framework;
using Microsoft.Build.ProjectCache;
using TaskItem = Microsoft.Build.Utilities.TaskItem;

internal sealed record DeclaredFile(string Path, string Hash);
internal sealed record DeclaredProject(string Identity, string[] Dependencies);
internal sealed record Session(string Workspace, string Cache, string Scratch, string Report, string Entry, string Toolchain,
    DeclaredFile[] Files, Dictionary<string, DeclaredProject> Projects, string? Remote = null, string? TargetsPath = null);
internal sealed record CachedItem(string Spec, Dictionary<string, string> Metadata);
internal sealed record Results(string Project, string Key, Dictionary<string, CachedItem[]> Targets, string? Inputs = null, string? Toolchain = null);
internal sealed record Ready(string Bundle, string Api);
internal sealed class State
{
    public TaskCompletionSource<Ready> Completion { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public string? Key { get; set; }
    public string[] Requested { get; set; } = [];
}

// Explicit-input, package-free experimental cache; the owned probe is its only entry point.
public sealed class NativeCachePlugin : ProjectCachePluginBase
{
    private Session session = null!;
    private RemoteBundles? remote;
    private Dictionary<string, State> states = [];
    private readonly ConcurrentBag<object> events = [];
    private readonly ConcurrentBag<(string Source, string Destination)> pending = [];
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true, RespectRequiredConstructorParameters = true, RespectNullableAnnotations = true, AllowDuplicateProperties = false };
    private static string Hash(string value) => Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(value)));
    private string Relative(string path) => Path.GetRelativePath(session.Workspace, path);
    private string Normalize(string value) => value.Replace(session.Workspace, "${WORKSPACE}", StringComparison.Ordinal);
    private string Property(string key, string value) => key == "DirectoryBuildTargetsPath" && session.TargetsPath is not null && value == session.TargetsPath ? "${CACHE_TARGETS}" : Normalize(value);
    private string Expand(string value) => value.Replace("${WORKSPACE}", session.Workspace, StringComparison.Ordinal);
    private static string Assembly(string project) => Path.GetFileNameWithoutExtension(project);
    private static string Bin(string project) => Path.Combine(Path.GetDirectoryName(project)!, "bin/Release/net10.0");
    private static string Reference(string project) => Path.Combine(Path.GetDirectoryName(project)!, "obj/Release/net10.0/ref", Assembly(project) + ".dll");

    public override Task BeginBuildAsync(CacheContext context, PluginLoggerBase logger, CancellationToken token)
    {
        session = JsonSerializer.Deserialize<Session>(File.ReadAllText(Environment.GetEnvironmentVariable("NATIVE_CACHE_SESSION")!), Json)!;
        if (context.Graph is null || !Directory.Exists(session.Scratch) || !session.Projects.ContainsKey(session.Entry))
            throw new InvalidDataException("native cache requires a qualified graph session");
        states = session.Projects.Keys.ToDictionary(project => project, _ => new State());
        if (!context.Graph.ProjectNodes.Select(node => Relative(node.ProjectInstance.FullPath)).Order().SequenceEqual(states.Keys.Order()))
            throw new InvalidDataException("declared and evaluated projects differ");
        foreach (var node in context.Graph.ProjectNodes)
        {
            var project = Relative(node.ProjectInstance.FullPath);
            if (node.ProjectInstance.GetPropertyValue("TargetFramework") != "net10.0" ||
                node.ProjectInstance.GetPropertyValue("Configuration") != "Release" ||
                node.ProjectInstance.GetPropertyValue("NETCoreSdkVersion") != "10.0.400" ||
                !node.ProjectReferences.Select(child => Relative(child.ProjectInstance.FullPath)).Order().SequenceEqual(session.Projects[project].Dependencies.Order()))
                throw new InvalidDataException("unqualified project configuration or edges");
        }
        VerifyInputs();
        if (session.Remote is not null) remote = new RemoteBundles(session.Remote, message => events.Add(new { kind = "remote", message }));
        return Task.CompletedTask;
    }

    private void VerifyInputs()
    {
        foreach (var file in session.Files)
            if (!Files.ValidRelativePath(file.Path) || Files.Hash(Path.Combine(session.Workspace, file.Path)) != file.Hash)
                throw new InvalidDataException("declared input changed: " + file.Path);
        var observed = Directory.EnumerateFiles(session.Workspace, "*", SearchOption.AllDirectories)
            .Select(Relative).Where(path => !path.Split('/').Contains("bin") && !path.Contains("/obj/Release/", StringComparison.Ordinal)).Order();
        if (!observed.SequenceEqual(session.Files.Select(file => file.Path).Order()))
            throw new InvalidDataException("input namespace changed");
    }

    public override async Task<CacheResult> GetCacheResultAsync(BuildRequestData request, PluginLoggerBase logger, CancellationToken token)
    {
        var project = Relative(request.ProjectInstance!.FullPath);
        var state = states[project];
        var dependencies = new List<string>();
        foreach (var dependency in session.Projects[project].Dependencies.Order())
        {
            var ready = await states[dependency].Completion.Task.WaitAsync(token);
            dependencies.Add(dependency + ":" + ready.Api);
        }
        state.Requested = request.TargetNames.ToArray();
        state.Key = Hash(JsonSerializer.Serialize(new
        {
            policy = "native-qualified-v2",
            project,
            session.Toolchain,
            inputs = session.Projects[project].Identity,
            properties = request.ProjectInstance.GlobalProperties.OrderBy(pair => pair.Key).Select(pair => new[] { pair.Key, Property(pair.Key, pair.Value) }),
            targets = request.TargetNames.Order(),
            dependencies
        }));
        var candidate = Path.Combine(session.Cache, state.Key);
        if (!Directory.Exists(candidate) && remote is not null) await remote.Fetch(state.Key, candidate, token);
        if (Directory.Exists(candidate))
        {
            try
            {
                var artifacts = CompileBoundary.Validate(candidate);
                var results = JsonSerializer.Deserialize<Results>(File.ReadAllText(Path.Combine(candidate, "results.json")), Json) ?? throw new InvalidDataException("empty cached results");
                if (results.Targets.Any(pair => pair.Value is null || pair.Value.Any(item => item is null || item.Metadata is null || item.Metadata.Values.Any(value => value is null))) || results.Key != state.Key || results.Project != project || results.Inputs != session.Projects[project].Identity || results.Toolchain != session.Toolchain || request.TargetNames.Any(target => !results.Targets.ContainsKey(target)))
                    throw new InvalidDataException("cached target identity mismatch");
                foreach (var artifact in artifacts)
                {
                    if (!Allowed(project, artifact.Path)) throw new InvalidDataException("artifact outside own project outputs");
                    Files.Copy(Path.Combine(candidate, "artifacts", artifact.Path), Path.Combine(session.Workspace, artifact.Path));
                }
                var ready = new Ready(candidate, Files.Hash(Path.Combine(candidate, "artifacts", Reference(project))));
                state.Completion.SetResult(ready);
                events.Add(new { project, kind = "hit", key = state.Key });
                return CacheResult.IndicateCacheHit(results.Targets.Select(pair => new PluginTargetResult(pair.Key,
                    pair.Value.Select(item =>
                    {
                        ITaskItem2 result = new TaskItem();
                        result.EvaluatedIncludeEscaped = Expand(item.Spec);
                        foreach (var metadata in item.Metadata) result.SetMetadata(metadata.Key, Expand(metadata.Value));
                        return result;
                    }).ToArray(), BuildResultCode.Success)).ToArray());
            }
            catch (Exception error) when (error is IOException or InvalidDataException or JsonException)
            {
                events.Add(new { project, kind = "rejected", reason = error.Message });
            }
        }
        // Never rely on timestamp incrementality after a content-key miss.
        foreach (var directory in new[] { Bin(project), Path.Combine(Path.GetDirectoryName(project)!, "obj/Release") })
            if (Directory.Exists(Path.Combine(session.Workspace, directory))) Directory.Delete(Path.Combine(session.Workspace, directory), true);
        events.Add(new { project, kind = "miss", key = state.Key });
        return CacheResult.IndicateNonCacheHit(CacheResultType.CacheMiss);
    }

    private static bool Allowed(string project, string path) => path == Reference(project) ||
        new[] { ".dll", ".pdb", ".xml", ".deps.json", ".runtimeconfig.json" }.Any(extension => path == Path.Combine(Bin(project), Assembly(project) + extension));

    public override Task HandleProjectFinishedAsync(FileAccessContext context, BuildResult result, PluginLoggerBase logger, CancellationToken token)
    {
        var project = Relative(context.ProjectFullPath);
        var state = states[project];
        if (state.Completion.Task.IsCompleted) return Task.CompletedTask;
        try
        {
            if (result.OverallResult != BuildResultCode.Success || state.Key is null) throw new InvalidDataException("project build failed");
            var targets = result.ResultsByTarget.Where(pair => pair.Value.ResultCode == TargetResultCode.Success).ToDictionary(pair => pair.Key, pair =>
                pair.Value.Items.Select(item => new CachedItem(Normalize(((ITaskItem2)item).EvaluatedIncludeEscaped),
                    ((ITaskItem2)item).CloneCustomMetadataEscaped().Keys.Cast<string>().ToDictionary(name => name, name => Normalize(((ITaskItem2)item).GetMetadataValueEscaped(name))))).ToArray());
            if (state.Requested.Any(target => !targets.ContainsKey(target))) throw new InvalidDataException("requested target result missing");
            var bundle = Path.Combine(session.Scratch, state.Key);
            Directory.CreateDirectory(bundle);
            foreach (var file in Directory.EnumerateFiles(Path.Combine(session.Workspace, Path.GetDirectoryName(project)!), "*", SearchOption.AllDirectories))
            {
                var relative = Relative(file);
                if (Allowed(project, relative)) Files.Copy(file, Path.Combine(bundle, "artifacts", relative));
            }
            KeepOwnRuntimeMetadata(bundle, project);
            File.WriteAllText(Path.Combine(bundle, "results.json"), JsonSerializer.Serialize(new Results(project, state.Key, targets, session.Projects[project].Identity, session.Toolchain), Json));
            CompileBoundary.Seal(bundle);
            var api = Files.Hash(Path.Combine(bundle, "artifacts", Reference(project)));
            pending.Add((bundle, Path.Combine(session.Cache, state.Key)));
            state.Completion.SetResult(new Ready(bundle, api));
        }
        catch (Exception error)
        {
            state.Completion.TrySetException(error);
            throw;
        }
        return Task.CompletedTask;
    }

    private void KeepOwnRuntimeMetadata(string bundle, string project)
    {
        var path = Path.Combine(bundle, "artifacts", Bin(project), Assembly(project) + ".deps.json");
        var metadata = JsonNode.Parse(File.ReadAllText(path))!;
        var target = metadata["runtimeTarget"]!["name"]!.GetValue<string>();
        var libraries = metadata["libraries"]!.AsObject();
        var own = Assembly(project) + "/1.0.0";
        if (libraries[own]?["type"]?.GetValue<string>() != "project") throw new InvalidDataException("unqualified own runtime library");
        foreach (var library in libraries)
        {
            var type = library.Value!["type"]!.GetValue<string>();
            var id = library.Key.Split('/')[0];
            if (type == "reference" && id.EndsWith(".Reference", StringComparison.Ordinal)) id = id[..^10];
            if (type is not ("project" or "reference") || !states.Keys.Any(value => Assembly(value) == id))
                throw new InvalidDataException("unqualified dependency runtime library");
        }
        // Each producer contributes its own SDK metadata. Recompose the graph
        // from current producers, excluding SDK aliases of copied dependencies.
        metadata["libraries"] = new JsonObject { [own] = libraries[own]!.DeepClone() };
        metadata["targets"] = new JsonObject { [target] = new JsonObject { [own] = metadata["targets"]![target]![own]!.DeepClone() } };
        File.WriteAllText(path, metadata.ToJsonString(Json));
    }

    public override async Task EndBuildAsync(PluginLoggerBase logger, CancellationToken token)
    {
        try
        {
            if (states.Values.Any(state => !state.Completion.Task.IsCompletedSuccessfully)) throw new InvalidDataException("incomplete graph; no cache publication");
            VerifyInputs();
            var own = await states[session.Entry].Completion.Task;
            var dependencies = await Task.WhenAll(states.Where(pair => pair.Key != session.Entry).Select(pair => pair.Value.Completion.Task));
            var composed = Path.Combine(session.Scratch, "runtime");
            CompileBoundary.Assemble(new RuntimeAssemblyRequest(own.Bundle, dependencies.Select(value => value.Bundle).ToArray(), composed));
            Files.CopyTree(Path.Combine(composed, "artifacts", Bin(session.Entry)), Path.Combine(session.Workspace, Bin(session.Entry)));
            Directory.CreateDirectory(session.Cache);
            foreach (var (source, destination) in pending)
            {
                // The qualified driver holds the cache lock for the whole session.
                if (Directory.Exists(destination)) Directory.Delete(destination, true);
                Directory.Move(source, destination);
                if (remote is not null) await remote.Publish(Path.GetFileName(destination), destination, token);
            }
        }
        finally
        {
            remote?.Dispose();
            File.WriteAllText(session.Report, JsonSerializer.Serialize(events.ToArray(), Json));
        }
    }
}
