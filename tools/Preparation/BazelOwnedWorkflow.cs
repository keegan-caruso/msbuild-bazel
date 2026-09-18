using System.Diagnostics;
using System.Text;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

// Bazel owns preparation and build inputs. The controller stages declared data
// and gates publication; it does not evaluate projects or scan runtime content.
internal static class BazelOwnedWorkflow
{
    private static readonly string[] Tools = ["Preparation", "GraphExport", "EvaluationProbe", "ReplayPlugin", "ActionRunner", "NativeProjectCache", "TestRunner"];
    private static readonly string[] Policies = ["pilot-package-policy.json", "discovery-test-packages.json", "discovery-sdk-imports.json"];
    private static string Tool(string root, string name) => Path.Combine(root, "tools", name, "bin/Release/net10.0", name + ".dll");
    public static void Prepare(JsonNode request)
    {
        var output = Path.GetFullPath(request.String("output")); var scratch = Path.Combine(output, ".work");
        var root = Path.Combine(scratch, "repository"); var workspace = Path.Combine(scratch, "workspace");
        var diagnostics = Path.GetFullPath(request.String("diagnostics")); Directory.CreateDirectory(diagnostics);
        var clock = Stopwatch.StartNew();
        void CopyInputs(string field, string destination)
        {
            Directory.CreateDirectory(destination);
            foreach (var item in request.Array(field)) Host.Copy(item!.String("source"), Path.Combine(destination, Host.Safe(item.String("destination"))));
        }
        try
        {
            CopyInputs("controller", root); CopyInputs("sources", workspace);
            Directory.CreateDirectory(Path.Combine(workspace, ".nuget/packages"));
            foreach (var path in FileTree.Files(workspace).Where(FileTree.RestoreMetadata))
                File.WriteAllText(path, File.ReadAllText(path).Replace("${WORKSPACE}", workspace, StringComparison.Ordinal));
            var sdk = Host.Real(Path.GetDirectoryName(Environment.ProcessPath!)!);
            var runtime = new Dictionary<string, JsonObject>(StringComparer.Ordinal);
            foreach (var path in request.Array("runtimeRoots").Select(n => n!.GetValue<string>())) runtime[path] = FileTree.Snapshot(path, true);
            var runtimeIdentity = new JsonObject(); foreach (var (path, snapshot) in runtime) runtimeIdentity[path] = Json.Digest(snapshot);
            var toolchain = Json.Digest(new JsonObject { ["policy"] = "bazel-owned-preparation-v1", ["runtime"] = runtimeIdentity, ["controller"] = Json.Digest(FileTree.Snapshot(root)), ["host"] = Json.Read(request.String("host")) });
            var discovery = new Discovery(root, sdk, workspace, Path.Combine(scratch, "discovery"), toolchain, runtime, declaredRuntimeRoots: runtime.Keys.ToArray());
            var graph = discovery.Capture(request.String("entry")); NativePlan.Qualify(graph);
            var graphPath = Path.Combine(scratch, "graph.json"); Json.Write(graphPath, graph);
            var prepared = Path.Combine(scratch, "prepared");
            var bound = Tools.ToDictionary(name => name, name => Tool(root, name), StringComparer.Ordinal);
            GraphPreparation.Run(new JsonObject { ["schemaVersion"] = 1, ["repository"] = root, ["workspace"] = workspace, ["manifest"] = graphPath, ["output"] = prepared, ["sdkRoot"] = sdk, ["sdkVersion"] = "10.0.400" }, bound, () => discovery.Export(request.String("entry")));
            NativePlan.Materialize(prepared, graph, output, toolchain); discovery.Verify();
            Json.Write(Path.Combine(diagnostics, "report.json"), new JsonObject { ["accepted"] = true, ["seconds"] = clock.Elapsed.TotalSeconds, ["projects"] = graph.Array("nodes").Count });
        }
        finally { FileTree.Remove(scratch); }
    }
    public static JsonNode Run(JsonNode request)
    {
        var allowed = new HashSet<string>(["schemaVersion", "repository", "sdkRoot", "bazel", "workspace", "state", "entry", "output", "operation", "tests", "nuget-packages", "bazel-remote-cache", "bazel-remote-upload", "remote-endpoint", "remote-snapshot", "bazel-install-cache", "bazel-repository-cache"], StringComparer.Ordinal);
        if (request["schemaVersion"]?.GetValue<int>() != 1 || request.AsObject().Any(p => !allowed.Contains(p.Key))) throw new InvalidDataException("Invalid Bazel-owned workflow request");
        var root = Host.Real(request.String("repository")); var source = Host.Real(request.String("workspace")); var state = Host.Real(request.String("state")); var output = Host.Real(request.String("output"));
        foreach (var (a, b) in new[] { (root, source), (root, state), (source, state), (output, source), (output, root), (output, state) })
            if (Host.Within(a, b) || Host.Within(b, a)) throw new InvalidDataException("Workflow paths must be disjoint");
        if (Host.Real(AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar)) != Host.Real(Path.GetDirectoryName(Tool(root, "Preparation"))!)) throw new InvalidDataException("Request repository must own the loaded controller");
        var sdk = Host.Real(request.String("sdkRoot")); var bazel = request.String("bazel"); var entry = Host.Safe(request.String("entry"));
        if (!OperatingSystem.IsMacOS() || sdk != "/nix/store/f3kvj2nc26gn7rh5mnfnaa2dgy2p10v3-dotnet-sdk-10.0.400/share/dotnet") throw new InvalidDataException("Bazel-owned preparation currently requires the qualified macOS Nix SDK");
        var operation = request.String("operation"); var tests = request["tests"];
        if (operation is not ("build" or "test") || operation == "test" && tests is null) throw new InvalidDataException("Invalid operation/test declaration");
        if (Path.Exists(output)) throw new IOException("Output exists"); Directory.CreateDirectory(output);
        using var lease = Host.Lock(Path.Combine(state, "lease"));
        var owner = Path.Combine(state, "owner.json");
        if (!File.Exists(owner))
        {
            if (Directory.EnumerateFileSystemEntries(state).Any(p => Path.GetFileName(p) != "lease")) throw new InvalidDataException("Unowned workflow state");
            Json.Write(owner, new JsonObject { ["policy"] = "bazel-owned-workflow-v1" });
        }
        if (Json.Read(owner).String("policy") != "bazel-owned-workflow-v1") throw new InvalidDataException("Wrong workflow state owner");
        var timer = Stopwatch.StartNew(); var phases = new JsonObject(); var report = new JsonObject { ["accepted"] = false, ["phases"] = phases, ["sdkContentScansInController"] = 0 };
        T Measure<T>(string name, Func<T> action) { var watch = Stopwatch.StartNew(); try { return action(); } finally { phases[name] = watch.Elapsed.TotalSeconds; } }
        ActionCache? gate = null; using var remote = request["remote-endpoint"] is { } endpoint ? new RemoteCache(endpoint.GetValue<string>()) : null;
        try
        {
            var generated = Path.Combine(state, "g"); Directory.CreateDirectory(generated);
            var sourceIdentity = FileTree.Snapshot(source);
            var controllerOriginal = Tools.ToDictionary(name => Path.Combine(root, "tools", name, "bin/Release/net10.0"), name => FileTree.Snapshot(Path.Combine(root, "tools", name, "bin/Release/net10.0")));
            var roots = Host.Run("/nix/var/nix/profiles/default/bin/nix-store", ["-qR", Path.GetDirectoryName(Path.GetDirectoryName(sdk))!], root).Split('\n', StringSplitOptions.RemoveEmptyEntries).Order(StringComparer.Ordinal).ToArray();
            var inputs = Path.Combine(generated, "inputs");
            report["nuget"] = Measure("stagePackages", () => NuGetInputs.Stage(source, inputs, Host.Real(request.String("nuget-packages"))));
            foreach (var path in FileTree.Files(inputs).Where(FileTree.RestoreMetadata))
            {
                var text = File.ReadAllText(path).Replace(inputs, "${WORKSPACE}", StringComparison.Ordinal);
                if (Path.GetFileName(path) == "project.nuget.cache")
                {
                    var receipt = JsonNode.Parse(text)!;
                    if (receipt["success"]?.GetValue<bool>() != true) throw new InvalidDataException("Unsuccessful restore");
                    if (receipt.AsObject().ContainsKey("dgSpecHash")) receipt["dgSpecHash"] = "$NORMALIZED";
                    text = Json.Canonical(receipt);
                }
                File.WriteAllText(path, text);
            }
            var controller = Path.Combine(generated, "controller"); FileTree.Remove(controller); Directory.CreateDirectory(controller);
            foreach (var name in Tools) FileTree.Copy(Path.Combine(root, "tools", name, "bin/Release/net10.0"), Path.Combine(controller, "tools", name, "bin/Release/net10.0"));
            Host.Copy(Path.Combine(root, "tools/GraphExport/Bazel.GraphExport.targets"), Path.Combine(controller, "tools/GraphExport/Bazel.GraphExport.targets"));
            foreach (var name in Policies) Host.Copy(Path.Combine(root, "tools", name), Path.Combine(controller, "tools", name));
            foreach (var extension in new[] { "props", "targets" }) Host.Copy(Path.Combine(root, "tools/ActionRunner/Build/Action." + extension), Path.Combine(controller, "tools/ActionRunner/Build/Action." + extension));
            foreach (var name in new[] { "msbuild.bzl", "graph.bzl" }) Host.Copy(Path.Combine(root, "bazel", name), Path.Combine(controller, "bazel", name));
            var worker = WorkerIdentity.Capture(Json.Digest(new JsonObject { ["controller"] = Json.Digest(FileTree.Snapshot(controller)), ["sdkRecipe"] = sdk, ["runtimeRoots"] = Json.Strings(roots) }), bazel, root, true);
            worker["inputOwnership"] = "bazel-owned-preparation-v1"; report["worker"] = worker.DeepClone(); Json.Write(Path.Combine(generated, "host.json"), worker);
            var seeds = Path.Combine(generated, "seeds"); FileTree.Remove(seeds); Directory.CreateDirectory(seeds);
            var cache = Path.Combine(state, "cache"); if (Directory.Exists(cache)) FileTree.Copy(cache, seeds, preserveModes: false);
            if (request["remote-snapshot"] is { } snapshot)
            {
                if (remote is null) throw new InvalidDataException("Snapshot requires endpoint");
                var catalog = remote.Snapshot(snapshot.GetValue<string>(), worker); remote.Seeds(catalog["projects"]!, null, seeds);
            }
            Generate(root, generated, sdk, roots, entry, tests);
            var watched = new[] { inputs, controller, seeds }.Concat(tests is null ? [] : new[] { Path.Combine(generated, "test-data") }).ToDictionary(p => p, p => FileTree.Snapshot(p));
            var watchedFiles = Directory.GetFiles(generated).ToDictionary(p => p, p => Json.Sha(File.ReadAllBytes(p)));
            var command = new List<string> { "--nosystem_rc", "--nohome_rc", "--noworkspace_rc", "--output_base=" + Path.Combine(state, "b"), "--output_user_root=" + Path.Combine(state, "u"), operation, "//:" + operation, "--incompatible_autoload_externally=", "--lockfile_mode=error", "--jobs=2", "--spawn_strategy=darwin-sandbox", "--strategy=MsbuildPrepare=local", "--execution_log_json_file=" + Path.Combine(output, "execution.json"), "--noshow_progress", "--color=no", "--curses=no" };
            if (request["bazel-install-cache"] is { } install)
            {
                var path = Path.Combine(Host.Real(install.GetValue<string>()), FileTree.HashRegular(Host.Real(bazel)).Digest); Directory.CreateDirectory(path);
                command.Insert(5, "--install_base=" + path); report["bazelInstallBase"] = path;
            }
            if (request["bazel-repository-cache"] is { } repositoryCache) command.Add("--repository_cache=" + Host.Real(repositoryCache.GetValue<string>()));
            if (operation == "test") command.AddRange(["--cache_test_results=no", "--test_output=errors"]);
            if (request["bazel-remote-cache"] is { } actionEndpoint)
            {
                gate = new ActionCache(actionEndpoint.GetValue<string>(), Path.Combine(state, "pending-actions"), request["bazel-remote-upload"]?.GetValue<bool>() == true);
                command.AddRange(["--remote_cache=" + gate.Url, "--remote_upload_local_results=" + (request["bazel-remote-upload"]?.GetValue<bool>() == true ? "true" : "false"), "--remote_cache_async=false", "--remote_verify_downloads=true", "--remote_download_outputs=all"]);
            }
            else if (request["bazel-remote-upload"]?.GetValue<bool>() == true) throw new InvalidDataException("Upload requires cache endpoint");
            var code = Measure("bazel", () => NativeWorkflow.Execute(bazel, command, generated, Path.Combine(output, "bazel.log"))); report["exitCode"] = code;
            var events = File.Exists(Path.Combine(output, "execution.json")) ? NativeWorkflow.Events(File.ReadAllBytes(Path.Combine(output, "execution.json"))).ToArray() : [];
            foreach (var mnemonic in new[] { "MsbuildPrepare", "MsbuildNativeCache" })
            {
                var actions = events.Where(n => n["mnemonic"]?.GetValue<string>() == mnemonic).ToArray();
                var executed = actions.Where(n => n["cacheHit"]?.GetValue<bool>() != true).ToArray();
                if (mnemonic == "MsbuildNativeCache" && executed.Any(n => n["runner"]?.GetValue<string>() != "darwin-sandbox")) throw new InvalidDataException("Native sandbox required");
                report[mnemonic] = new JsonObject { ["executed"] = executed.Length, ["remoteHits"] = actions.Count(n => n["cacheHit"]?.GetValue<bool>() == true && n["runner"]?.GetValue<string>() == "remote cache hit") };
            }
            if (code != 0) throw new InvalidDataException("Bazel action/test failed; see bazel.log");
            report["compiles"] = report["MsbuildNativeCache"]!["executed"]!.GetValue<int>() == 0 ? 0 : Json.Read(Path.Combine(generated, "bazel-bin/build.diagnostics/action.json"))["compiles"]!.DeepClone();
            if (operation == "test")
            {
                var testReport = Path.Combine(generated, "bazel-testlogs/test/test.outputs/report.json"); report["test"] = Json.Read(testReport);
                if (report["test"]!["passed"]?.GetValue<bool>() != true || report["test"]!["buildOrRestoreInvoked"]?.GetValue<bool>() != false) throw new InvalidDataException("Test acceptance failed");
            }
            var bundle = Host.Real(Path.Combine(generated, "bazel-bin/build.bundle"));
            var bundleCache = Path.Combine(bundle, "cache");
            string Content(string path) => Json.Digest(new JsonObject(FileTree.Files(path).Select(p => KeyValuePair.Create<string, JsonNode?>(Path.GetRelativePath(path, p), JsonValue.Create(Json.Sha(File.ReadAllBytes(p)))))));
            if (request["bazel-remote-upload"]?.GetValue<bool>() == true && Content(seeds) != Content(bundleCache))
                Measure("primeActionCache", () =>
                {
                    // Prime the complete seed variant only after the original build/test
                    // passed. Both action publications remain behind the same gate.
                    foreach (var (path, expected) in watched) FileTree.Verify(path, expected);
                    foreach (var (path, hash) in watchedFiles) if (Json.Sha(File.ReadAllBytes(path)) != hash) throw new InvalidDataException("Declared controller input changed");
                    var expectedCache = Content(bundleCache); var expectedApp = FileTree.Snapshot(Path.Combine(bundle, "app"));
                    FileTree.Remove(seeds); FileTree.Copy(bundleCache, seeds, preserveModes: false);
                    watched[seeds] = FileTree.Snapshot(seeds);
                    Generate(root, generated, sdk, roots, entry, tests);
                    watchedFiles = Directory.GetFiles(generated).ToDictionary(p => p, p => Json.Sha(File.ReadAllBytes(p)));
                    var primeLog = Path.Combine(output, "prime-execution.json");
                    var primeCommand = command.Select(argument => argument == operation ? "build" : argument == "//:" + operation ? "//:build" : argument.StartsWith("--execution_log_json_file=", StringComparison.Ordinal) ? "--execution_log_json_file=" + primeLog : argument)
                        .Where(argument => !argument.StartsWith("--test_output=", StringComparison.Ordinal) && !argument.StartsWith("--cache_test_results=", StringComparison.Ordinal)).ToList();
                    if (NativeWorkflow.Execute(bazel, primeCommand, generated, Path.Combine(output, "prime-bazel.log")) != 0) throw new InvalidDataException("Seeded cache priming failed");
                    var executed = NativeWorkflow.Events(File.ReadAllBytes(primeLog)).Where(n => n["mnemonic"]?.GetValue<string>() == "MsbuildNativeCache" && n["cacheHit"]?.GetValue<bool>() != true).ToArray();
                    if (executed.Any(n => n["runner"]?.GetValue<string>() != "darwin-sandbox")) throw new InvalidDataException("Priming requires native sandbox");
                    var compiles = executed.Length == 0 ? 0 : Json.Read(Path.Combine(generated, "bazel-bin/build.diagnostics/action.json"))["compiles"]!.GetValue<int>();
                    if (compiles != 0 || Content(bundleCache) != expectedCache) throw new InvalidDataException("Priming changed accepted project bundles");
                    FileTree.Verify(Path.Combine(bundle, "app"), expectedApp);
                    report["cachePrime"] = new JsonObject { ["accepted"] = true, ["compiles"] = compiles };
                    return true;
                });
            Measure("leaseExit", () =>
            {
                WorkerIdentity.RequireCompatible(worker, CaptureSameWorker(worker, bazel, root));
                FileTree.Verify(source, sourceIdentity);
                foreach (var (path, expected) in watched.Concat(controllerOriginal)) FileTree.Verify(path, expected);
                foreach (var (path, hash) in watchedFiles) if (Json.Sha(File.ReadAllBytes(path)) != hash) throw new InvalidDataException("Declared controller input changed");
                return true;
            });
            foreach (var folder in Directory.GetDirectories(bundleCache)) RemoteCache.ValidateBundle(FileTree.Files(folder).ToDictionary(p => Path.GetRelativePath(folder, p), File.ReadAllBytes));
            FileTree.Remove(cache); FileTree.Copy(bundleCache, cache, preserveModes: false);
            if (remote is not null) report["publishedSnapshot"] = remote.Publish(cache, null, null, worker);
            gate?.Publish(); report["accepted"] = true;
        }
        finally
        {
            if (gate is not null) { gate.Dispose(); report["actionCache"] = gate.Statistics; }
            if (remote is not null) report["remoteTransport"] = remote.Statistics;
            FileTree.Remove(Path.Combine(state, "pending-actions")); report["seconds"] = timer.Elapsed.TotalSeconds; Json.Write(Path.Combine(output, "report.json"), report);
        }
        return report;
    }
    private static JsonObject CaptureSameWorker(JsonObject previous, string bazel, string root)
    {
        var worker = WorkerIdentity.Capture(previous.String("controllerSdkClosure"), bazel, root, true); worker["inputOwnership"] = "bazel-owned-preparation-v1"; return worker;
    }
    private static void Generate(string root, string generated, string sdk, string[] runtimeRoots, string entry, JsonNode? tests)
    {
        foreach (var name in new[] { "msbuild.bzl", "native_cache.bzl", "native_test.bzl", "preparation.bzl" }) Host.Copy(Path.Combine(root, "bazel", name), Path.Combine(generated, name));
        Host.Copy(Path.Combine(root, "bazel/native.MODULE.bazel.lock"), Path.Combine(generated, "MODULE.bazel.lock"));
        File.WriteAllText(Path.Combine(generated, "MODULE.bazel"), "module(name = \"native_msbuild_workflow\")\nbazel_dep(name = \"platforms\", version = \"0.0.11\")\nlocal_dotnet_sdk = use_repo_rule(\"//:msbuild.bzl\", \"local_dotnet_sdk\")\n" + Starlark.Call("local_dotnet_sdk", new JsonObject { ["name"] = "dotnet", ["path"] = sdk, ["runtime_roots"] = Json.Strings(runtimeRoots) }));
        JsonArray Files(string directory) => Json.Strings(FileTree.Files(Path.Combine(generated, directory)).Select(p => Path.GetRelativePath(generated, p)));
        var build = "load(\":preparation.bzl\", \"msbuild_prepare\")\nload(\":native_cache.bzl\", \"msbuild_native_cache\")\nload(\":native_test.bzl\", \"native_test\")\n";
        build += Starlark.Call("msbuild_prepare", new JsonObject { ["name"] = "prepare", ["project"] = entry, ["srcs"] = Files("inputs"), ["controller"] = Files("controller"), ["runner"] = "controller/tools/Preparation/bin/Release/net10.0/Preparation.dll", ["host"] = "host.json", ["runtime_roots"] = Json.Strings(runtimeRoots), ["sdk"] = "@dotnet//:files", ["dotnet"] = "@dotnet//:sdk/dotnet" });
        build += Starlark.Call("msbuild_native_cache", new JsonObject { ["name"] = "build", ["project"] = entry, ["prepared_plan"] = ":prepare", ["seeds"] = Files("seeds"), ["runner"] = "controller/tools/NativeProjectCache/bin/Release/net10.0/NativeProjectCache.dll", ["runner_support"] = Files("controller").DeepClone(), ["sdk"] = "@dotnet//:files", ["dotnet"] = "@dotnet//:sdk/dotnet" });
        if (tests is not null)
        {
            var data = new JsonArray(); var hashes = new JsonObject(); var testData = Path.Combine(generated, "test-data"); FileTree.Remove(testData); Directory.CreateDirectory(testData);
            foreach (var item in tests.Array("data"))
            {
                var name = Host.Safe(item!.GetValue<string>()); var bytes = FileTree.ReadRegular(Path.Combine(generated, "inputs", name));
                var path = Path.Combine(testData, name); Directory.CreateDirectory(Path.GetDirectoryName(path)!); File.WriteAllBytes(path, bytes); data.Add("test-data/" + name); hashes[name] = Json.Sha(bytes);
            }
            build += Starlark.Call("native_test", new JsonObject { ["name"] = "test", ["subject"] = ":build", ["project"] = entry, ["prepared_plan"] = ":prepare", ["global_properties"] = new JsonObject { ["configuration"] = "Release", ["targetframework"] = "net10.0" }, ["runtime_directory"] = Path.Combine(Path.GetDirectoryName(entry)!, "bin/Release/net10.0"), ["assembly"] = Path.GetFileNameWithoutExtension(entry) + ".dll", ["data"] = data, ["data_hashes"] = hashes, ["expected_tests"] = tests["expectedTests"]!.DeepClone(), ["runner"] = "controller/tools/TestRunner/bin/Release/net10.0/TestRunner.dll", ["runner_support"] = Files("controller").DeepClone(), ["host_identity"] = "host.json", ["sdk"] = "@dotnet//:files", ["dotnet"] = "@dotnet//:sdk/dotnet", ["size"] = "small", ["timeout"] = "moderate" });
        }
        File.WriteAllText(Path.Combine(generated, "BUILD.bazel"), build);
    }
}
