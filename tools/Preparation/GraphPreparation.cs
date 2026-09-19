using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace RulesMSBuild.Preparation;

internal sealed class GraphPreparation
{
    private readonly string root;
    private readonly string workspace;
    private readonly string sdk;
    private readonly string version;
    private readonly string output;
    private readonly JsonNode request;
    private readonly JsonNode graph;
    private readonly Dictionary<string, JsonNode> nodes;
    private readonly Dictionary<string, HashSet<string>> closures;
    private readonly Packages packages;
    private readonly IReadOnlyDictionary<string, string>? prebuilt;
    private readonly Func<JsonNode>? revalidate;
    private readonly IntegrityProfile? profile;
    private readonly bool packageMetadataOnly;

    private GraphPreparation(JsonNode request, string output, IReadOnlyDictionary<string, string>? prebuilt, Func<JsonNode>? revalidate, IntegrityProfile? profile, bool packageMetadataOnly)
    {
        this.request = request;
        this.profile = profile;
        this.packageMetadataOnly = packageMetadataOnly;
        this.prebuilt = prebuilt;
        this.revalidate = revalidate;
        this.output = output;
        root = Host.Real(request.String("repository"));
        workspace = Host.Real(request.String("workspace"));
        sdk = Host.Real(request["sdkRoot"]?.GetValue<string>() ?? Environment.GetEnvironmentVariable("RULES_MSBUILD_DOTNET_ROOT") ?? Path.Combine(root, ".tools/dotnet"));
        version = request["sdkVersion"]?.GetValue<string>() ?? Json.Read(Path.Combine(root, "global.json"))["sdk"]!.String("version");
        if (!Regex.IsMatch(version, "^[0-9A-Za-z][0-9A-Za-z.\\-]*$")) throw new InvalidDataException("invalid SDK version input");
        graph = Json.Read(request.String("manifest"));
        var expected = new JsonObject { ["sdkVersion"] = version, ["graphEngine"] = "ProjectGraph", ["contractVersion"] = 1 };
        if (graph["schemaVersion"]?.GetValue<int>() != 1 || !JsonNode.DeepEquals(graph["toolchain"], expected)) throw new InvalidDataException("unsupported graph schema");
        nodes = new(StringComparer.Ordinal);
        foreach (var node in graph.Array("nodes"))
            if (node is null || !nodes.TryAdd(node.String("id"), node)) throw new InvalidDataException("duplicate or empty graph nodes");
        if (nodes.Count == 0) throw new InvalidDataException("duplicate or empty graph nodes");
        packages = new(workspace, output, root, writePayload: !packageMetadataOnly);
        ValidateNodes();
        closures = Closures(nodes);
    }
    public static void Run(JsonNode request, IReadOnlyDictionary<string, string>? prebuilt = null, Func<JsonNode>? revalidate = null, IntegrityProfile? profile = null, bool packageMetadataOnly = false)
    {
        var allowed = new HashSet<string>(["schemaVersion", "repository", "workspace", "manifest", "output", "sdkRoot", "sdkVersion", "toolTargetFramework", "msbuildEngineRoot", "tests", "compileBoundary"], StringComparer.Ordinal);
        if (request["schemaVersion"]?.GetValue<int>() != 1 || request.AsObject().Any(p => !allowed.Contains(p.Key))) throw new InvalidDataException("unsupported preparation request");
        var output = Host.Real(request.String("output"));
        if (Path.Exists(output)) throw new IOException("Output already exists: " + output);
        var source = Host.Real(request.String("workspace"));
        if (Host.Within(output, source)) throw new InvalidDataException("preparation output must be outside source");
        Directory.CreateDirectory(Path.GetDirectoryName(output)!);
        using var lease = Host.Lock(Path.Combine(Host.Real(request.String("repository")), "artifacts/graph-preparation.lock"));
        var temporary = Path.Combine(Path.GetDirectoryName(output)!, ".graph-prepare-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(temporary);
        try
        {
            var stage = Path.Combine(temporary, "workspace");
            var preparation = new GraphPreparation(request, stage, prebuilt, revalidate, profile, packageMetadataOnly);
            preparation.Prepare();
            // Directory.Move refuses to overwrite even an empty committed directory.
            Directory.Move(stage, output);
        }
        finally { Directory.Delete(temporary, true); }
    }
    private static string[] Dependencies(JsonNode node) => node.Array("dependencies").Select(n => n!.GetValue<string>()).ToArray();
    internal static Dictionary<string, HashSet<string>> Closures(Dictionary<string, JsonNode> nodes)
    {
        var dependencies = nodes.ToDictionary(p => p.Key, p => Dependencies(p.Value).ToHashSet(StringComparer.Ordinal), StringComparer.Ordinal);
        var consumers = nodes.Keys.ToDictionary(k => k, _ => new List<string>(), StringComparer.Ordinal);
        foreach (var (id, required) in dependencies)
            foreach (var dependency in required)
            {
                if (!consumers.TryGetValue(dependency, out var parents)) throw new InvalidDataException("missing dependency node");
                parents.Add(id);
            }
        var pending = dependencies.ToDictionary(p => p.Key, p => p.Value.Count, StringComparer.Ordinal);
        var ready = new Queue<string>(pending.Where(p => p.Value == 0).Select(p => p.Key));
        var result = new Dictionary<string, HashSet<string>>(StringComparer.Ordinal);
        while (ready.TryDequeue(out var id))
        {
            var reachable = new HashSet<string>([id], StringComparer.Ordinal);
            foreach (var dependency in dependencies[id]) reachable.UnionWith(result[dependency]);
            result[id] = reachable;
            foreach (var consumer in consumers[id]) if (--pending[consumer] == 0) ready.Enqueue(consumer);
        }
        if (result.Count != nodes.Count) throw new InvalidDataException("cyclic graph");
        return result;
    }
    internal static JsonNode Execution(JsonNode node)
    {
        if (node["execution"] is { } explicitExecution) return explicitExecution;
        var directory = Path.GetDirectoryName(Host.Relative(node.String("project")))!;
        var framework = node.String("targetFramework");
        string Logical(string path) => "workspace/" + Path.Combine(directory, path);
        return new JsonObject { ["assetsFile"] = Logical("obj/project.assets.json"), ["outputDirectory"] = Logical("bin/Release/" + framework), ["referenceDirectory"] = Logical("obj/Release/" + framework + "/ref") };
    }
    private void ValidateNodes()
    {
        var directories = new HashSet<string>(StringComparer.Ordinal);
        foreach (var (id, node) in nodes)
        {
            if (!Regex.IsMatch(id, "^[0-9a-f]{24}$")) throw new InvalidDataException("invalid configured node id");
            var properties = node["globalProperties"]!.AsObject();
            var framework = node.String("targetFramework");
            if (properties["configuration"]?.GetValue<string>() != "Release" || properties.Any(p => p.Key is not ("configuration" or "targetframework" or "flavor" or "nbgv_cachemode" or "publicrelease")) || framework is not ("net10.0" or "net8.0" or "netstandard2.0") || (properties["targetframework"]?.GetValue<string>() ?? framework) != framework)
                throw new InvalidDataException("unsupported graph execution configuration");
            if ((properties["nbgv_cachemode"]?.GetValue<string>() ?? "None").ToLowerInvariant() != "none" || (properties["publicrelease"]?.GetValue<string>() ?? "false").ToLowerInvariant() is not ("true" or "false")) throw new InvalidDataException("unsupported graph versioning configuration");
            var project = Host.Relative(node.String("project"));
            var execution = Execution(node);
            foreach (var (key, prefix) in new[] { ("assetsFile", "obj"), ("outputDirectory", "bin"), ("referenceDirectory", "obj") })
                if (!Host.Within(Host.Relative(execution.String(key)), Path.Combine(Path.GetDirectoryName(project)!, prefix))) throw new InvalidDataException("unsupported graph output layout");
            var outputs = node.Array("outputs");
            if (outputs.Count != 1 || outputs[0]!.String("kind") != "assembly" || Path.GetDirectoryName(Host.Relative(outputs[0]!.String("path"))) != Host.Relative(execution.String("outputDirectory"))) throw new InvalidDataException("unsupported graph output layout");
            if (Dependencies(node).Any(d => !nodes.ContainsKey(d))) throw new InvalidDataException("missing dependency node");
            packages.Plan(project, Host.Relative(execution.String("assetsFile")), framework);
            if (node["execution"] is not null)
                foreach (var key in new[] { "outputDirectory", "referenceDirectory" })
                {
                    var path = Host.Relative(execution.String(key));
                    if (!directories.Add(path)) throw new InvalidDataException("configured-output-collision: " + path);
                }
        }
        foreach (var path in directories)
        {
            var parent = Path.GetDirectoryName(path);
            while (!string.IsNullOrEmpty(parent))
            {
                if (directories.Contains(parent)) throw new InvalidDataException("configured-output-collision: " + path);
                parent = Path.GetDirectoryName(parent);
            }
        }
        if (graph.Array("entryPoints").Count == 0 || graph.Array("entryPoints").Any(n => !nodes.ContainsKey(n!.GetValue<string>()))) throw new InvalidDataException("invalid entry points");
    }
    private string[] ValidateInputs()
    {
        var roots = new Dictionary<string, string> { ["workspace"] = workspace, ["dotnet"] = sdk, ["packages"] = Path.Combine(workspace, ".nuget/packages"), ["adapter"] = Path.Combine(root, "tools/GraphExport"), ["nix"] = "/nix/store" };
        var external = new HashSet<string>(StringComparer.Ordinal);
        var hashes = new Dictionary<(string Path, bool Normalized), string>();
        foreach (var itemNode in (graph["graphInputs"] as JsonArray ?? []).Concat(nodes.Values.SelectMany(n => n.Array("inputs"))))
        {
            var item = itemNode!; var path = item.String("path"); var kind = item.String("kind"); var parts = path.Split('/', 2);
            if (parts.Length != 2 || !roots.TryGetValue(parts[0], out var inputRoot)) throw new InvalidDataException("unsafe input path: " + path);
            var logical = Host.Safe(parts[1]);
            if (parts[0] == "nix")
            {
                if (kind != "import" || !Host.Within(sdk, "/nix/store") || !Regex.IsMatch(logical.Split('/')[0], "^[0-9abcdfghijklmnpqrsvwxyz]{32}-[^/]+$")) throw new InvalidDataException("unsupported Nix SDK import: " + path);
                external.Add("/nix/store/" + logical);
            }
            var source = Path.Combine(inputRoot, logical);
            if (!File.Exists(source) || (parts[0] is "workspace" or "nix") && !Host.Within(Host.Real(source), inputRoot)) throw new InvalidDataException("missing-input: missing or escaping input: " + path);
            if (parts[0] == "workspace" && ("/" + logical).Contains("/obj/", StringComparison.Ordinal) && kind is not ("restore" or "import")) throw new InvalidDataException("unsupported declared obj input: " + path);
            var normalized = kind == "restore" || kind == "import" && new[] { ".json", ".props", ".targets", ".xml", ".proj", ".csproj" }.Contains(Path.GetExtension(source).ToLowerInvariant());
            if (!hashes.TryGetValue((source, normalized), out var digest))
            {
                if (normalized)
                {
                    var text = File.ReadAllText(source);
                    if (Path.GetFileName(source) == "project.nuget.cache")
                    {
                        var cache = JsonNode.Parse(text)!;
                        if (cache.AsObject().ContainsKey("dgSpecHash")) cache["dgSpecHash"] = "$NORMALIZED";
                        text = cache.ToJsonString();
                    }
                    digest = Json.Sha(Encoding.UTF8.GetBytes(text.Replace(workspace, "$WORKSPACE", StringComparison.Ordinal).Replace(Path.Combine(workspace, ".nuget/packages"), "$PACKAGES", StringComparison.Ordinal).Replace(sdk, "$DOTNET", StringComparison.Ordinal)));
                }
                else digest = FileTree.HashRegular(Host.Real(source)).Digest;
                hashes.Add((source, normalized), digest);
            }
            // Compare every expectation, even when the same file occurs in many projects.
            // The independent graph export and discovery lease verification still follow.
            if (digest != item.String("sha256")) throw new InvalidDataException((kind == "package" ? "hash-mismatch: " : "stale-manifest: ") + "stale graph input: " + path);
        }
        return external.Order(StringComparer.Ordinal).ToArray();
    }
    private void Prepare()
    {
        var phase = IntegrityProfile.Begin();
        var external = ValidateInputs();
        profile?.End("prepareValidateInputs", phase); phase = IntegrityProfile.Begin();
        if (graph["entryRequests"] is not JsonArray { Count: > 0 }) throw new InvalidDataException("graph discovery request missing; regenerate manifest");
        var compileBoundary = request["compileBoundary"]?.GetValue<bool>() ?? false;
        if (compileBoundary) CompileBoundary.Validate(workspace, graph, packages);
        Directory.CreateDirectory(output);
        var engine = Path.Combine(sdk, "sdk", version, "MSBuild.dll");
        if (!File.Exists(engine)) throw new InvalidDataException("selected SDK engine missing: " + engine);
        var environment = Host.SdkEnvironment(sdk, version);
        if (prebuilt is not null) environment["MSBuildEnableWorkloadResolver"] = "false";
        var tests = request["tests"] as JsonArray;
        var built = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var name in new[] { "GraphExport", "ReplayPlugin", "ActionRunner" }.Concat(tests is { Count: > 0 } ? ["TestRunner"] : Array.Empty<string>()))
        {
            if (prebuilt is not null)
            {
                var bound = prebuilt[name];
                if (!File.Exists(bound)) throw new InvalidDataException("Missing bound tool: " + name);
                built[name] = bound;
                continue;
            }
            var arguments = new List<string> { "exec", engine, Path.Combine(root, "tools", name), "-restore", "-target:Build", "-property:Configuration=Release", "-nologo", "-getProperty:TargetPath,TargetFramework" };
            if (name is "GraphExport" or "ReplayPlugin")
            {
                if (request["toolTargetFramework"] is { } framework)
                {
                    if (framework.GetValue<string>() is not ("net10.0" or "net11.0")) throw new InvalidDataException("unsupported tool target framework");
                    arguments.Add("-property:RulesMSBuildToolTargetFramework=" + framework.GetValue<string>());
                }
                if (request["msbuildEngineRoot"] is { } engineRoot) arguments.Add("-property:RulesMSBuildEngineRoot=" + Host.Real(engineRoot.GetValue<string>()));
            }
            var log = Host.Run(Path.Combine(sdk, "dotnet"), arguments, root, environment);
            File.WriteAllText(Path.Combine(output, name + "-build.log"), log);
            var start = log.LastIndexOf("\n{", StringComparison.Ordinal);
            var properties = JsonNode.Parse(start >= 0 ? log[(start + 1)..] : log)!["Properties"]!;
            var target = properties.String("TargetPath");
            if (properties.String("TargetFramework") is not ("net10.0" or "net11.0") || !Path.IsPathRooted(target) || Path.GetFileName(target) != name + ".dll" || !File.Exists(target)) throw new InvalidDataException("missing or invalid built tool output: " + target);
            built[name] = target;
        }
        var discoveryRequest = Path.Combine(Path.GetDirectoryName(output)!, "discovery-request.json");
        var refreshed = Path.Combine(Path.GetDirectoryName(output)!, "discovery.json");
        Json.Write(discoveryRequest, new JsonObject { ["schemaVersion"] = 1, ["workspace"] = workspace, ["dotnetRoot"] = sdk, ["sdkVersion"] = version, ["packageRoot"] = Path.Combine(workspace, ".nuget/packages"), ["entryPoints"] = graph["entryRequests"]!.DeepClone(), ["output"] = refreshed });
        if (revalidate is not null) Json.Write(refreshed, revalidate());
        else Host.Run(Path.Combine(sdk, "dotnet"), [built["GraphExport"], "--request", discoveryRequest], workspace, environment);
        if (!JsonNode.DeepEquals(Json.Read(refreshed), graph)) throw new InvalidDataException("stale-manifest: stale graph discovery: regenerate manifest");
        profile?.End("prepareRevalidateGraph", phase); phase = IntegrityProfile.Begin();
        Host.Copy(built["ReplayPlugin"], Path.Combine(output, "ReplayPlugin.dll"));
        foreach (var suffix in new[] { ".dll", ".deps.json", ".runtimeconfig.json" }) Host.Copy(Path.ChangeExtension(built["ActionRunner"], null) + suffix, Path.Combine(output, "runner/ActionRunner" + suffix));
        foreach (var extension in new[] { "props", "targets" })
        {
            var contents = File.ReadAllText(Path.Combine(root, "tools/ActionRunner/Build/Action." + extension));
            var filename = "Directory.Build." + extension;
            var property = "_GraphDirectoryBuild" + (extension == "props" ? "Props" : "Targets");
            var original = "<Import Project=\"$(RULES_MSBUILD_REPLAY_WORKSPACE)/" + filename + "\" />";
            var replacement = "<PropertyGroup><" + property + ">$([MSBuild]::GetPathOfFileAbove('" + filename + "', '$(MSBuildProjectDirectory)/'))</" + property + "></PropertyGroup><Import Project=\"$(" + property + ")\" Condition=\"'$(" + property + ")' != ''\" />";
            contents = contents.Replace(original, replacement, StringComparison.Ordinal);
            if (extension == "targets") contents = contents.Replace("</Project>", "<Target Name=\"GraphCompileEvidence\" BeforeTargets=\"CoreCompile\"><Message Importance=\"high\" Text=\"RULES_MSBUILD_COMPILE:$(RULES_MSBUILD_GRAPH_PROJECT)\" /></Target></Project>", StringComparison.Ordinal);
            File.WriteAllText(Path.Combine(output, "runner/Action." + extension), contents);
        }
        foreach (var name in new[] { "msbuild.bzl", "graph.bzl" }) Host.Copy(Path.Combine(root, "bazel", name), Path.Combine(output, name));
        File.WriteAllText(Path.Combine(output, "MODULE.bazel"), "module(name = \"msbuild_graph\")\n\nlocal_dotnet_sdk = use_repo_rule(\"//:msbuild.bzl\", \"local_dotnet_sdk\")\n" + Starlark.Call("local_dotnet_sdk", new JsonObject { ["name"] = "dotnet", ["path"] = sdk, ["external_imports"] = Json.Strings(external) }));
        Json.Write(Path.Combine(output, "host-identity.json"), new JsonObject { ["platform"] = RuntimeInformation.OSDescription, ["machine"] = RuntimeInformation.OSArchitecture.ToString(), ["dotnet"] = sdk, ["policyRevision"] = 2, ["controller"] = "dotnet-preparation-v1" });
        Directory.CreateDirectory(Path.Combine(output, "restore"));
        profile?.End("prepareSupport", phase); phase = IntegrityProfile.Begin();
        WriteBuild(tests, compileBoundary, built.GetValueOrDefault("TestRunner"));
        profile?.End("prepareWriteBuild", phase);
        Json.Write(Path.Combine(output, "graph.json"), graph);
    }
    internal static JsonObject FrameworkSelections(Dictionary<string, JsonNode> nodes, HashSet<string> closure)
    {
        var selections = new JsonObject();
        var split = new HashSet<string>(StringComparer.Ordinal);
        var ambiguous = closure.Any(id => nodes[id].String("project").Contains('|'));
        foreach (var id in closure.Order(StringComparer.Ordinal))
        {
            var node = nodes[id]; var references = new JsonObject();
            foreach (var target in Execution(node)["selectedReferences"] as JsonArray ?? [])
            {
                var project = Host.Relative(target!.String("project")); var framework = target.String("targetFramework");
                if (!Dependencies(node).Any(d => Host.Relative(nodes[d].String("project")) == project && nodes[d].String("targetFramework") == framework)) throw new InvalidDataException("unsupported-configuration: selected reference differs from dependency");
                if (references[project] is { } prior && prior.GetValue<string>() != framework) throw new InvalidDataException("unsupported-configuration: conflicting selected reference frameworks");
                references[project] = framework;
            }
            var path = Host.Relative(node.String("project"));
            var selection = new JsonObject { ["target_framework"] = node.String("targetFramework"), ["references"] = references, ["remove_framework_global"] = node["globalProperties"]?["targetframework"] is null };
            if (selections[path] is { } previous && !JsonNode.DeepEquals(previous, selection))
            {
                selections.Remove(path); previous["project"] = path; selections[path + "|" + previous.String("target_framework")] = previous; split.Add(path);
            }
            if (ambiguous ? selections.Any(p => p.Key.StartsWith(path + "|", StringComparison.Ordinal)) : split.Contains(path)) { selection["project"] = path; path += "|" + selection.String("target_framework"); }
            if (selections[path] is { } existing && !JsonNode.DeepEquals(existing, selection)) throw new InvalidDataException("unsupported-configuration: conflicting selected framework edges");
            selections[path] = selection;
        }
        return selections;
    }
    private void WriteBuild(JsonArray? tests, bool compileBoundary, string? testRunner)
    {
        var build = new StringBuilder("load(\":graph.bzl\", \"graph_project\")\n");
        if (tests is { Count: > 0 }) build.Append("load(\":graph_test.bzl\", \"graph_test\")\n");
        var restored = new HashSet<string>(StringComparer.Ordinal); var copied = new HashSet<string>(StringComparer.Ordinal);
        foreach (var (id, node) in nodes.OrderBy(p => p.Key, StringComparer.Ordinal))
        {
            var sources = new HashSet<string>(StringComparer.Ordinal); var restore = new List<string>();
            foreach (var reachable in closures[id].Order(StringComparer.Ordinal))
            {
                var dependency = nodes[reachable];
                foreach (var item in dependency.Array("inputs"))
                    if (item!.String("path").StartsWith("workspace/", StringComparison.Ordinal) && item.String("kind") is not ("restore" or "package") && (reachable == id || item.String("kind") is "project" or "import" or "extra" or "signing" or "content"))
                    {
                        var source = Host.Relative(item.String("path")); if (!source.Contains("/obj/", StringComparison.Ordinal)) sources.Add(source);
                    }
                var path = "restore/" + reachable + ".json"; restore.Add(path);
                if (!restored.Add(reachable)) continue;
                var state = new JsonObject();
                foreach (var source in Directory.GetFiles(Path.GetDirectoryName(Path.Combine(workspace, Host.Relative(Execution(dependency).String("assetsFile"))))!).Order(StringComparer.Ordinal))
                {
                    if (Path.GetExtension(source) is not (".json" or ".props" or ".targets") && Path.GetFileName(source) != "project.nuget.cache") continue;
                    var contents = Encoding.UTF8.GetString(File.ReadAllBytes(source)).Replace("\r\n", "\n", StringComparison.Ordinal).Replace('\r', '\n');
                    if (Path.GetFileName(source) == "project.nuget.cache")
                    {
                        var cache = JsonNode.Parse(contents)!; if (cache.AsObject().ContainsKey("dgSpecHash")) cache["dgSpecHash"] = "$NORMALIZED"; contents = Json.Canonical(cache);
                    }
                    state[Path.GetRelativePath(workspace, source)] = contents.Replace(workspace, "${WORKSPACE}", StringComparison.Ordinal).Replace(sdk, "${SDK}", StringComparison.Ordinal);
                }
                Json.Write(Path.Combine(output, path), state);
            }
            foreach (var name in new[] { "global.json", "NuGet.Config", "Directory.Build.props", "Directory.Build.targets" }) if (File.Exists(Path.Combine(workspace, name))) sources.Add(name);
            foreach (var source in sources) if (copied.Add(source)) Host.Copy(Path.Combine(workspace, source), Path.Combine(output, "src", source));
            var execution = Execution(node);
            var (manifest, packagePaths) = packages.Stage(Host.Relative(node.String("project")), Host.Relative(execution.String("assetsFile")), node.String("targetFramework"), id);
            if (packageMetadataOnly) continue;
            var attributes = new JsonObject
            {
                ["sdk_version"] = version,
                ["plugin"] = "ReplayPlugin.dll",
                ["build_props"] = "runner/Action.props",
                ["build_targets"] = "runner/Action.targets",
                ["runner"] = "runner/ActionRunner.dll",
                ["runner_support"] = Json.Strings(["runner/ActionRunner.deps.json", "runner/ActionRunner.runtimeconfig.json"]),
                ["sdk"] = "@dotnet//:files",
                ["dotnet"] = "@dotnet//:sdk/dotnet",
                ["host_identity"] = "host-identity.json",
                ["name"] = "node_" + id,
                ["project"] = Host.Relative(node.String("project")),
                ["compile_boundary"] = compileBoundary,
                ["framework_selections"] = Json.Canonical(FrameworkSelections(nodes, closures[id])),
                ["global_properties"] = node["globalProperties"]!.DeepClone(),
                ["packages"] = Json.Strings(packagePaths),
                ["package_manifest"] = manifest,
                ["srcs"] = Json.Strings(sources.Select(s => "src/" + s).Order(StringComparer.Ordinal)),
                ["restore"] = Json.Strings(restore),
                ["dependencies"] = Json.Strings(Dependencies(node).Order(StringComparer.Ordinal).Select(d => ":node_" + d))
            };
            if (node["execution"] is not null) { attributes["assets_file"] = Host.Relative(execution.String("assetsFile")); attributes["output_directories"] = Json.Strings(new[] { "outputDirectory", "referenceDirectory" }.Select(k => Host.Relative(execution.String(k)))); }
            build.Append(Starlark.Call("graph_project", attributes));
        }
        packages.Verify();
        if (packageMetadataOnly) return;
        build.Append(Starlark.Call("filegroup", new JsonObject { ["name"] = "all", ["srcs"] = Json.Strings(graph.Array("entryPoints").Select(n => ":node_" + n!.GetValue<string>()).Order(StringComparer.Ordinal)) }));
        if (tests is { Count: > 0 }) build.Append(TestDeclarations.Write(workspace, output, root, nodes, tests, testRunner!));
        File.WriteAllText(Path.Combine(output, "BUILD.bazel"), build.ToString());
    }
}
