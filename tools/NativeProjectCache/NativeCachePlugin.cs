using System.Collections.Concurrent;
using System.Text.Json;
using System.Text.Json.Nodes;
using ActionRunner;
using Microsoft.Build.Execution;
using Microsoft.Build.Framework;
using Microsoft.Build.ProjectCache;
using TaskItem = Microsoft.Build.Utilities.TaskItem;

internal sealed record DeclaredFile(string Path, string Hash);
internal sealed record DeclaredProject(string Identity, string[] Dependencies, string TargetFramework = "net10.0", bool Implementation = false, string[]? Analyzers = null, bool OrchardModule = false, bool OrchardApplication = false);
internal sealed record Session(string Workspace, string Cache, string Scratch, string Report, string Entry, string Toolchain,
    DeclaredFile[] Files, Dictionary<string, DeclaredProject> Projects, string? Remote = null, string? TargetsPath = null, string Policy = "native-qualified-v2", Dictionary<string, string>? Prebuilt = null);
internal sealed record Ready(string Bundle, string Api);
internal sealed class State
{
    public TaskCompletionSource<Ready> Completion { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    public string? Key { get; set; }
    public string[] Requested { get; set; } = [];
}

// Explicit-input cache for the qualified owned and evaluated graph policies.
public sealed class NativeCachePlugin : ProjectCachePluginBase
{
    private Session session = null!;
    private RemoteBundles? remote;
    private bool apiRuntime;
    private Dictionary<string, State> states = [];
    private CompileBoundary.ValidationScope dependencyValidation = new();
    private HashSet<string> prebuiltBundles = [];
    private readonly ConcurrentBag<object> events = [];
    private readonly ConcurrentBag<(string Source, string Destination)> pending = [];
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true, RespectRequiredConstructorParameters = true, RespectNullableAnnotations = true, AllowDuplicateProperties = false };
    private static string Hash(string value) => Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(value)));
    private string Relative(string path) => Path.GetRelativePath(session.Workspace, path);
    private string Normalize(string value) => value.Replace(session.Workspace, "${WORKSPACE}", StringComparison.Ordinal);
    private string Property(string key, string value) => key == "DirectoryBuildTargetsPath" && session.TargetsPath is not null && value == session.TargetsPath ? "${CACHE_TARGETS}" : Normalize(value);
    private string Expand(string value) => value.Replace("${WORKSPACE}", session.Workspace, StringComparison.Ordinal);
    private static string Assembly(string project) => Path.GetFileNameWithoutExtension(project);
    private string Bin(string project) => Path.Combine(Path.GetDirectoryName(project)!, "bin/Release", session.Projects[project].TargetFramework);
    private bool PackagePolicy => session.Policy == "evaluated-api-runtime-v2";
    private string[] Closure(string project)
    {
        var selected = new HashSet<string>(StringComparer.Ordinal);
        void Visit(string current)
        {
            if (!selected.Add(current)) return;
            foreach (var dependency in session.Projects[current].Dependencies) Visit(dependency);
        }
        Visit(project);
        return selected.Order(StringComparer.Ordinal).ToArray();
    }
    private string DependencyIdentity(string bundle, string project) => apiRuntime
        ? EvaluatedBoundary.Identity(bundle, project, Closure(project), session.Projects[project].Dependencies.Order(StringComparer.Ordinal)
            .Select(dependency => dependency + ":" + states[dependency].Completion.Task.Result.Api).ToArray(), runtimeReferences: session.Prebuilt is not null, fullImplementation: session.Projects[project].Implementation, validate: ValidateBundle)
        : Files.Hash(Path.Combine(bundle, PackagePolicy ? "artifacts.json" : Path.Combine("artifacts", Reference(project))));
    private void Compose(string bundle, string project, bool verifySelection = false) => EvaluatedBoundary.Compose(bundle, project,
        Closure(project).Where(dependency => dependency != project).ToDictionary(dependency => dependency,
            dependency => states[dependency].Completion.Task.Result.Bundle), session.Workspace, verifySelection, ValidateBundle);
    // Private captured bundles remain sealed until the exit verification and move.
    private Artifact[] ValidateBundle(string bundle) => prebuiltBundles.Contains(bundle) ||
        session.Prebuilt is not null && bundle.StartsWith(session.Scratch + Path.DirectorySeparatorChar, StringComparison.Ordinal)
        ? dependencyValidation.Read(bundle) : CompileBoundary.Validate(bundle);
    private string Reference(string project) => Path.Combine(Path.GetDirectoryName(project)!, "obj/Release", session.Projects[project].TargetFramework, "ref", Assembly(project) + ".dll");

    public override Task BeginBuildAsync(CacheContext context, PluginLoggerBase logger, CancellationToken token)
    {
        using var profile = BuildProfile.Measure("pluginBegin");
        session = JsonSerializer.Deserialize<Session>(File.ReadAllText(Environment.GetEnvironmentVariable("NATIVE_CACHE_SESSION")!), Json)!;
        dependencyValidation = new();
        prebuiltBundles = [];
        if (session.Policy is not ("native-qualified-v2" or "evaluated-api-runtime-v2")) throw new InvalidDataException("unknown native cache policy");
        if ((context.Graph is null && session.Prebuilt is null) || !Directory.Exists(session.Scratch) || !session.Projects.ContainsKey(session.Entry))
            throw new InvalidDataException("native cache requires a qualified graph session");
        if (PackagePolicy && session.Projects.Keys.Select(Assembly).Distinct(StringComparer.OrdinalIgnoreCase).Count() != session.Projects.Count)
            throw new InvalidDataException("ambiguous project runtime assembly names");
        if (session.Projects.Values.Any(project => project.TargetFramework is not ("net10.0" or "netstandard2.0") ||
            project.TargetFramework == "netstandard2.0" && !project.Implementation ||
            project.Implementation && project.Dependencies.Any(dependency => !session.Projects.TryGetValue(dependency, out var producer) || !producer.Implementation) ||
            (project.Analyzers ?? []).Any(analyzer => !project.Dependencies.Contains(analyzer) || !session.Projects.TryGetValue(analyzer, out var producer) || !producer.Implementation)))
            throw new InvalidDataException("Invalid framework or analyzer declaration");
        states = session.Projects.Keys.ToDictionary(project => project, _ => new State());
        if (context.Graph is not null)
        {
            if (!context.Graph.ProjectNodes.Select(node => Relative(node.ProjectInstance.FullPath)).Order().SequenceEqual(states.Keys.Order()))
                throw new InvalidDataException("declared and evaluated projects differ");
            foreach (var node in context.Graph.ProjectNodes) ValidateProject(node.ProjectInstance, node.ProjectReferences.Select(child => Relative(child.ProjectInstance.FullPath)));
            apiRuntime = PackagePolicy && context.Graph.ProjectNodes.All(node => OrdinaryReferences(node.ProjectInstance));
        }
        else apiRuntime = PackagePolicy;
        if (session.Prebuilt is not null)
        {
            prebuiltBundles = session.Prebuilt.Values.ToHashSet(StringComparer.Ordinal);
            if (!apiRuntime || !session.Prebuilt.Keys.Order().SequenceEqual(states.Keys.Where(p => p != session.Entry).Order())) throw new InvalidDataException("Project actions require a complete API dependency set");
            var visiting = new HashSet<string>(StringComparer.Ordinal);
            void Load(string project)
            {
                if (states[project].Completion.Task.IsCompletedSuccessfully) return;
                if (!visiting.Add(project)) throw new InvalidDataException("Cyclic API dependencies");
                foreach (var child in session.Projects[project].Dependencies) Load(child);
                var bundle = session.Prebuilt[project];
                Artifact[] artifacts;
                using (BuildProfile.Measure("dependencyValidate")) artifacts = ValidateBundle(bundle);
                var results = ProjectActions.Read(bundle);
                var identity = DependencyIdentity(bundle, project);
                if (results.TargetFramework != session.Projects[project].TargetFramework || results.OrchardModule != session.Projects[project].OrchardModule || results.OrchardApplication != session.Projects[project].OrchardApplication || results.Project != project || results.Toolchain != session.Toolchain || results.Key != identity || results.Inputs != identity) throw new InvalidDataException("Invalid project API dependency: " + project);
                Dictionary<string, string> replacements;
                using (BuildProfile.Measure("dependencyCompose"))
                    replacements = EvaluatedBoundary.RuntimeReplacements(bundle, project,
                        Closure(project).Where(dependency => dependency != project).ToDictionary(dependency => dependency,
                            dependency => states[dependency].Completion.Task.Result.Bundle), validate: ValidateBundle);
                using (BuildProfile.Measure("dependencyRestore"))
                    foreach (var artifact in artifacts)
                    {
                        if (!Allowed(project, artifact.Path)) throw new InvalidDataException("API artifact outside project outputs");
                        StaticWebAssets.Restore(replacements.GetValueOrDefault(artifact.Path, Path.Combine(bundle, "artifacts", artifact.Path)), Path.Combine(session.Workspace, artifact.Path), session.Workspace, normalize: true);
                    }
                states[project].Completion.SetResult(new Ready(bundle, identity));
                visiting.Remove(project);
                events.Add(new { project, kind = "dependency", key = identity });
            }
            foreach (var project in session.Prebuilt.Keys) Load(project);
        }
        VerifyInputs();
        if (session.Remote is not null) remote = new RemoteBundles(session.Remote, message => events.Add(new { kind = "remote", message }));
        return Task.CompletedTask;
    }

    private void ValidateProject(ProjectInstance instance, IEnumerable<string>? graphEdges = null)
    {
        var project = Relative(instance.FullPath);
        if (!session.Projects.TryGetValue(project, out var declared) ||
            instance.GetPropertyValue("TargetFramework") != declared.TargetFramework || instance.GetPropertyValue("Configuration") != "Release" ||
            instance.GetPropertyValue("NETCoreSdkVersion") != "10.0.400" ||
            !(graphEdges ?? instance.GetItems("ProjectReference").Select(item => Relative(item.GetMetadataValue("FullPath"))).Distinct()).Order().SequenceEqual(declared.Dependencies.Order()))
            throw new InvalidDataException("unqualified project configuration or edges");
    }

    private bool OrdinaryReferences(ProjectInstance instance)
    {
        var runtimeNames = session.Projects.Keys.SelectMany(project => new[] { ".dll", ".pdb", ".xml" }
            .Select(extension => Assembly(project) + extension)).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var analyzers = (session.Projects[Relative(instance.FullPath)].Analyzers ?? []).ToHashSet(StringComparer.Ordinal);
        return instance.GetItems("ProjectReference").All(reference =>
            (analyzers.Contains(Relative(reference.GetMetadataValue("FullPath")))
                ? reference.GetMetadataValue("OutputItemType").Equals("Analyzer", StringComparison.OrdinalIgnoreCase) && reference.GetMetadataValue("ReferenceOutputAssembly").Equals("false", StringComparison.OrdinalIgnoreCase)
                : reference.GetMetadataValue("OutputItemType").Length == 0 && !reference.GetMetadataValue("ReferenceOutputAssembly").Equals("false", StringComparison.OrdinalIgnoreCase)) &&
            !reference.GetMetadataValue("EmbedInteropTypes").Equals("true", StringComparison.OrdinalIgnoreCase)) &&
            !instance.Items.Any(item => item.ItemType is "Content" or "None" or "Compile" or "EmbeddedResource" &&
                EvaluatedBoundary.CopiesProjectRuntime(item.GetMetadataValue("CopyToOutputDirectory"),
                    [item.EvaluatedInclude, item.GetMetadataValue("TargetPath"), item.GetMetadataValue("Link")], runtimeNames));
    }

    private void VerifyInputs()
    {
        using var profile = BuildProfile.Measure("verifyWorkspaceInputs");
        using (BuildProfile.Measure("verifyWorkspaceHashes"))
            foreach (var file in session.Files)
                if (!Files.ValidRelativePath(file.Path) || Files.Hash(Path.Combine(session.Workspace, file.Path)) != file.Hash)
                    throw new InvalidDataException("declared input changed: " + file.Path);
        var outputs = states.Keys.SelectMany(project => new[] { Bin(project) + "/", Path.Combine(Path.GetDirectoryName(project)!, "obj/Release") + "/" }
            .Concat(session.Projects[project].OrchardApplication ? new[] { Path.Combine(Path.GetDirectoryName(project)!, "Localization") + "/" } : [])).ToArray();
        var observed = Directory.EnumerateFiles(session.Workspace, "*", SearchOption.AllDirectories)
            .Select(Relative).Where(path => !outputs.Any(prefix => path.StartsWith(prefix, StringComparison.Ordinal))).Order();
        using (BuildProfile.Measure("verifyWorkspaceNamespace"))
            if (!observed.SequenceEqual(session.Files.Select(file => file.Path).Order()))
                throw new InvalidDataException("input namespace changed");
    }

    public override async Task<CacheResult> GetCacheResultAsync(BuildRequestData request, PluginLoggerBase logger, CancellationToken token)
    {
        var project = Relative(request.ProjectInstance!.FullPath);
        if (session.Prebuilt is not null)
        {
            if (project != session.Entry) throw new InvalidDataException("Dependency replay must not query the compile plugin");
            ValidateProject(request.ProjectInstance);
            if (!OrdinaryReferences(request.ProjectInstance)) throw new InvalidDataException("Project actions require declared ordinary or analyzer references");
            events.Add(new { project, kind = "entry-evaluated" });
        }
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
            policy = session.Policy,
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
                if (results.Targets.Any(pair => pair.Value is null || pair.Value.Any(item => item is null || item.Metadata is null || item.Metadata.Values.Any(value => value is null))) || results.TargetFramework != session.Projects[project].TargetFramework || results.OrchardModule != session.Projects[project].OrchardModule || results.OrchardApplication != session.Projects[project].OrchardApplication || results.Key != state.Key || results.Project != project || results.Inputs != session.Projects[project].Identity || results.Toolchain != session.Toolchain || request.TargetNames.Any(target => !results.Targets.ContainsKey(target)))
                    throw new InvalidDataException("cached target identity mismatch");
                foreach (var artifact in artifacts)
                {
                    if (!Allowed(project, artifact.Path)) throw new InvalidDataException("artifact outside own project outputs");
                    StaticWebAssets.Restore(Path.Combine(candidate, "artifacts", artifact.Path), Path.Combine(session.Workspace, artifact.Path), session.Workspace);
                }
                var ready = new Ready(candidate, DependencyIdentity(candidate, project));
                if (apiRuntime) Compose(candidate, project);
                state.Completion.SetResult(ready);
                events.Add(new { project, kind = "hit", key = state.Key });
                return Replay(results);
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

    private CacheResult Replay(Results results) => CacheResult.IndicateCacheHit(results.Targets.Select(pair => new PluginTargetResult(pair.Key,
        pair.Value.Select(item =>
        {
            ITaskItem2 result = new TaskItem(); result.EvaluatedIncludeEscaped = Expand(item.Spec);
            foreach (var metadata in item.Metadata) result.SetMetadata(metadata.Key, Expand(metadata.Value));
            return result;
        }).ToArray(), BuildResultCode.Success)).ToArray());

    private bool Allowed(string project, string path) => path == Reference(project) ||
        (PackagePolicy && StaticWebAssets.Intermediate(project, session.Projects[project].TargetFramework, path)) ||
        (PackagePolicy && path.StartsWith(Bin(project) + "/", StringComparison.Ordinal)) ||
        (PackagePolicy && session.Projects[project].OrchardApplication && path.StartsWith(Path.Combine(Path.GetDirectoryName(project)!, "Localization") + "/", StringComparison.Ordinal)) ||
        new[] { ".dll", ".pdb", ".xml", ".deps.json", ".runtimeconfig.json" }.Any(extension => path == Path.Combine(Bin(project), Assembly(project) + extension));

    public override Task HandleProjectFinishedAsync(FileAccessContext context, BuildResult result, PluginLoggerBase logger, CancellationToken token)
    {
        using var profile = BuildProfile.Measure("pluginCapture");
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
            using (BuildProfile.Measure("captureFiles"))
                foreach (var file in Directory.EnumerateFiles(Path.Combine(session.Workspace, Path.GetDirectoryName(project)!), "*", SearchOption.AllDirectories))
                {
                    var relative = Relative(file);
                    if (Allowed(project, relative)) StaticWebAssets.Capture(file, Path.Combine(bundle, "artifacts", relative), session.Workspace);
                }
            if (!PackagePolicy) KeepOwnRuntimeMetadata(bundle, project);
            File.WriteAllText(Path.Combine(bundle, "results.json"), JsonSerializer.Serialize(new Results(project, state.Key, targets, session.Projects[project].Identity, session.Toolchain, session.Projects[project].TargetFramework, session.Projects[project].OrchardModule, session.Projects[project].OrchardApplication), Json));
            using (BuildProfile.Measure("captureSeal")) CompileBoundary.Seal(bundle);
            if (apiRuntime) using (BuildProfile.Measure("captureCompose")) Compose(bundle, project, verifySelection: true);
            string api;
            using (BuildProfile.Measure("captureIdentity")) api = DependencyIdentity(bundle, project);
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
        var profile = BuildProfile.Measure("pluginEnd");
        try
        {
            if (states.Values.Any(state => !state.Completion.Task.IsCompletedSuccessfully)) throw new InvalidDataException("incomplete graph; no cache publication");
            VerifyInputs();
            if (apiRuntime) using (BuildProfile.Measure("endCompose")) Compose((await states[session.Entry].Completion.Task).Bundle, session.Entry);
            else if (!PackagePolicy)
            {
                var own = await states[session.Entry].Completion.Task;
                var dependencies = await Task.WhenAll(states.Where(pair => pair.Key != session.Entry).Select(pair => pair.Value.Completion.Task));
                var composed = Path.Combine(session.Scratch, "runtime");
                CompileBoundary.Assemble(new RuntimeAssemblyRequest(own.Bundle, dependencies.Select(value => value.Bundle).ToArray(), composed));
                Files.CopyTree(Path.Combine(composed, "artifacts", Bin(session.Entry)), Path.Combine(session.Workspace, Bin(session.Entry)));
            }
            var publication = pending.ToDictionary(item => item.Destination, item => item.Source, StringComparer.Ordinal);
            using (BuildProfile.Measure("endRefresh"))
                if (apiRuntime)
                    foreach (var (project, state) in states)
                    {
                        if (session.Prebuilt?.ContainsKey(project) == true) continue;
                        var ready = await state.Completion.Task;
                        var canonical = Path.Combine(session.Scratch, "canonical", state.Key!);
                        var dependencies = Closure(project).Where(dependency => dependency != project)
                            .ToDictionary(dependency => dependency, dependency => states[dependency].Completion.Task.Result.Bundle);
                        if (EvaluatedBoundary.RefreshBundle(ready.Bundle, project, dependencies, canonical, ValidateBundle))
                            publication[Path.Combine(session.Cache, state.Key!)] = canonical;
                    }
            using (BuildProfile.Measure("endDependencyRevalidation")) dependencyValidation.VerifyUnchanged();
            Directory.CreateDirectory(session.Cache);
            foreach (var (destination, source) in publication)
            {
                // The qualified driver holds the cache lock for the whole session.
                if (Directory.Exists(destination)) Directory.Delete(destination, true);
                Directory.Move(source, destination);
                if (remote is not null) await remote.Publish(Path.GetFileName(destination), destination, token);
            }
        }
        finally
        {
            profile.Dispose();
            BuildProfile.Save(".plugin.json");
            remote?.Dispose();
            File.WriteAllText(session.Report, JsonSerializer.Serialize(events.ToArray(), Json));
        }
    }
}
