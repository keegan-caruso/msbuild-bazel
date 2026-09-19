using System.Diagnostics;
using System.Text;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

// Bazel owns preparation and build inputs. The controller stages declared data
// and gates publication; it does not evaluate projects or scan runtime content.
internal static class BazelOwnedWorkflow
{
    private static readonly string[] Tools = ["Preparation", "GraphExport", "EvaluationProbe", "ReplayPlugin", "ActionRunner", "NativeProjectCache", "TestRunner"];
    private static readonly string[] Policies = ["pilot-package-policy.json", "discovery-test-packages.json", "discovery-sdk-imports.json", "orchard-discovery-policy.json"];
    private static string Tool(string root, string name) => Path.Combine(root, "tools", name, "bin/Release/net10.0", name + ".dll");
    public static void Prepare(JsonNode request)
    {
        var output = Path.GetFullPath(request.String("output")); var scratch = Path.Combine(output, ".work");
        var root = Path.Combine(scratch, "repository"); var workspace = Path.Combine(scratch, "workspace");
        var diagnostics = Path.GetFullPath(request.String("diagnostics")); Directory.CreateDirectory(diagnostics);
        var clock = Stopwatch.StartNew(); var profile = new IntegrityProfile(); var phase = IntegrityProfile.Begin();
        void CopyInputs(string field, string destination)
        {
            Directory.CreateDirectory(destination);
            foreach (var item in request.Array(field))
            {
                var path = Path.Combine(destination, Host.Safe(item!.String("destination"))); Host.Copy(item.String("source"), path);
                FileTree.SetMode(path, FileTree.Mode(path) | UnixFileMode.UserWrite);
            }
        }
        try
        {
            CopyInputs("controller", root); CopyInputs("sources", workspace); PackageDirectories.Stage(request, workspace);
            foreach (var item in request.Array("sourceNames"))
            {
                var path = Path.Combine(workspace, Host.Safe(item!.GetValue<string>()));
                Directory.CreateDirectory(Path.GetDirectoryName(path)!); File.WriteAllBytes(path, []);
            }
            Directory.CreateDirectory(Path.Combine(workspace, ".nuget/packages"));
            foreach (var path in FileTree.Files(workspace).Where(FileTree.RestoreMetadata))
                File.WriteAllText(path, File.ReadAllText(path).Replace("${WORKSPACE}", workspace, StringComparison.Ordinal));
            profile.End("stageInputs", phase); phase = IntegrityProfile.Begin();
            var sdk = Host.Real(Path.GetDirectoryName(Environment.ProcessPath!)!);
            var runtime = new Dictionary<string, JsonObject>(StringComparer.Ordinal);
            foreach (var path in (request["runtimeManifest"] is { } runtimeManifest ? Json.Read(runtimeManifest.GetValue<string>()).AsArray() : request.Array("runtimeRoots")).Select(n => n!.GetValue<string>())) runtime[path] = FileTree.Snapshot(path, true);
            var runtimeIdentity = new JsonObject(); foreach (var (path, snapshot) in runtime) runtimeIdentity[path] = Json.Digest(snapshot);
            var toolchain = Json.Digest(new JsonObject { ["policy"] = "bazel-owned-preparation-v1", ["runtime"] = runtimeIdentity, ["controller"] = Json.Digest(FileTree.Snapshot(root)), ["host"] = Json.Read(request.String("host")) });
            profile.End("runtimeIdentity", phase); phase = IntegrityProfile.Begin();
            var discovery = new Discovery(root, sdk, workspace, Path.Combine(scratch, "discovery"), toolchain, runtime, declaredRuntimeRoots: runtime.Keys.ToArray());
            profile.End("discoverySetup", phase); phase = IntegrityProfile.Begin();
            var graph = discovery.Capture(request.String("entry"), profile); NativePlan.Qualify(graph);
            profile.End("discoveryCapture", phase); phase = IntegrityProfile.Begin();
            var graphPath = Path.Combine(scratch, "graph.json"); Json.Write(graphPath, graph);
            var prepared = Path.Combine(scratch, "prepared");
            var directPackages = request["packageDirectories"] is JsonArray { Count: > 0 };
            var bound = Tools.ToDictionary(name => name, name => Tool(root, name), StringComparer.Ordinal);
            GraphPreparation.Run(new JsonObject { ["schemaVersion"] = 1, ["repository"] = root, ["workspace"] = workspace, ["manifest"] = graphPath, ["output"] = prepared, ["sdkRoot"] = sdk, ["sdkVersion"] = "10.0.400" }, bound, discovery.RevalidateCaptured, profile, packageMetadataOnly: directPackages);
            profile.End("graphPreparation", phase); phase = IntegrityProfile.Begin();
            NativePlan.Materialize(prepared, graph, output, toolchain, includePayload: false, repository: root, packageSource: directPackages ? Path.Combine(workspace, ".nuget/packages") : null);
            profile.End("materialize", phase); phase = IntegrityProfile.Begin();
            if (request["projectOutputs"] is JsonObject projectOutputs) NativePlan.ProjectTemplates(output, projectOutputs);
            profile.End("projectTemplates", phase); phase = IntegrityProfile.Begin();
            discovery.Verify();
            profile.End("finalVerify", phase);
            NativePlan.RequireSourceOnly(graph, request.Array("sourceNames").Select(n => n!.GetValue<string>()).ToHashSet(StringComparer.Ordinal));
            Json.Write(Path.Combine(diagnostics, "report.json"), new JsonObject { ["accepted"] = true, ["seconds"] = clock.Elapsed.TotalSeconds, ["projects"] = graph.Array("nodes").Count, ["profile"] = profile.Report() });
        }
        finally { FileTree.Remove(scratch); }
    }
    public static JsonNode Run(JsonNode request)
    {
        var allowed = new HashSet<string>(["schemaVersion", "repository", "sdkRoot", "bazel", "workspace", "state", "entry", "output", "operation", "tests", "nuget-packages", "bazel-remote-cache", "bazel-remote-upload", "remote-endpoint", "remote-snapshot", "bazel-install-cache", "bazel-repository-cache", "project-actions", "project-layout", "direct-checkout", "locked-restore", "package-actions"], StringComparer.Ordinal);
        if (request["schemaVersion"]?.GetValue<int>() != 1 || request.AsObject().Any(p => !allowed.Contains(p.Key))) throw new InvalidDataException("Invalid Bazel-owned workflow request");
        var root = Host.Real(request.String("repository")); var source = Host.Real(request.String("workspace")); var state = Host.Real(request.String("state")); var output = Host.Real(request.String("output"));
        foreach (var (a, b) in new[] { (root, source), (root, state), (source, state), (output, source), (output, root), (output, state) })
            if (Host.Within(a, b) || Host.Within(b, a)) throw new InvalidDataException("Workflow paths must be disjoint");
        if (Host.Real(AppContext.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar)) != Host.Real(Path.GetDirectoryName(Tool(root, "Preparation"))!)) throw new InvalidDataException("Request repository must own the loaded controller");
        var sdk = Host.Real(request.String("sdkRoot")); var bazel = request.String("bazel"); var entry = Host.Safe(request.String("entry"));
        if (!OperatingSystem.IsMacOS() || sdk != "/nix/store/f3kvj2nc26gn7rh5mnfnaa2dgy2p10v3-dotnet-sdk-10.0.400/share/dotnet") throw new InvalidDataException("Bazel-owned preparation currently requires the qualified macOS Nix SDK");
        var projectActions = request["project-actions"]?.GetValue<bool>() == true;
        if (projectActions && (request["remote-snapshot"] is not null || request["remote-endpoint"] is not null)) throw new InvalidDataException("Project actions use bazel-remote-cache, not native snapshot endpoints");
        var directCheckout = request["direct-checkout"]?.GetValue<bool>() == true;
        if (directCheckout && !projectActions) throw new InvalidDataException("Direct checkout requires project actions");
        var lockedRestore = request["locked-restore"]?.GetValue<bool>() == true;
        if (lockedRestore && (!directCheckout || request["project-layout"] is null)) throw new InvalidDataException("Locked restore requires direct checkout and a declared project layout");
        var packageActions = request["package-actions"]?.GetValue<bool>() == true;
        if (packageActions && !lockedRestore) throw new InvalidDataException("Package actions require locked restore and a declared project layout");
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
        ActionCache? gate = null; using var remote = !projectActions && request["remote-endpoint"] is { } endpoint ? new RemoteCache(endpoint.GetValue<string>()) : null;
        try
        {
            var generated = Path.Combine(state, "g"); Directory.CreateDirectory(generated);
            var sourceIdentity = FileTree.Snapshot(source);
            var layoutPathInput = request["project-layout"]?.GetValue<string>();
            var layoutDigest = layoutPathInput is null ? null : FileTree.HashRegular(layoutPathInput).Digest;
            var declaredLayout = layoutPathInput is null ? null : ProjectLayout.Read(layoutPathInput, entry);
            if (declaredLayout is not null && !projectActions) throw new InvalidDataException("A declared layout requires project actions");
            var controllerOriginal = Tools.ToDictionary(name => Path.Combine(root, "tools", name, "bin/Release/net10.0"), name => FileTree.Snapshot(Path.Combine(root, "tools", name, "bin/Release/net10.0")));
            var inputs = Path.Combine(generated, "inputs");
            report["nuget"] = Measure("stagePackages", () => lockedRestore ? LockedRestore.Describe(source, declaredLayout!["projects"]!.AsObject().Select(pair => pair.Key)) : directCheckout ? NuGetInputs.Describe(source, Host.Real(request.String("nuget-packages")), sourceIdentity) : NuGetInputs.Stage(source, inputs, Host.Real(request.String("nuget-packages")), copyPackages: false));
            report["sourceStaging"] = directCheckout ? "direct-checkout" : "copied";
            report["restoreOwnership"] = lockedRestore ? "bazel-locked" : "external";
            foreach (var path in (directCheckout ? [] : FileTree.Files(inputs).Where(FileTree.RestoreMetadata)))
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
            var controllerFiles = Policies.Select(name => Path.Combine(root, "tools", name)).Concat(new[] { "tools/GraphExport/Bazel.GraphExport.targets", "tools/ActionRunner/Build/Action.props", "tools/ActionRunner/Build/Action.targets", "bazel/msbuild.bzl", "bazel/graph.bzl" }.Select(name => Path.Combine(root, name))).ToDictionary(path => path, path => Json.Sha(FileTree.ReadRegular(path)));
            var controllerIdentity = new JsonObject();
            foreach (var (path, original) in controllerOriginal) controllerIdentity[Path.GetRelativePath(root, path)] = Json.Digest(original);
            foreach (var (path, digest) in controllerFiles) controllerIdentity[Path.GetRelativePath(root, path)] = digest;
            var worker = WorkerIdentity.Capture(Json.Digest(new JsonObject { ["controller"] = controllerIdentity, ["sdkRecipe"] = sdk }), bazel, root, true);
            worker["inputOwnership"] = "bazel-owned-preparation-v1"; report["worker"] = worker.DeepClone(); Json.Write(Path.Combine(generated, "host.json"), worker);
            var seeds = Path.Combine(generated, "seeds"); FileTree.Remove(seeds); Directory.CreateDirectory(seeds);
            var cache = Path.Combine(state, "cache"); if (!projectActions && Directory.Exists(cache)) FileTree.Copy(cache, seeds, preserveModes: false);
            if (!projectActions && request["remote-snapshot"] is { } snapshot)
            {
                if (remote is null) throw new InvalidDataException("Snapshot requires endpoint");
                var catalog = remote.Snapshot(snapshot.GetValue<string>(), worker); remote.Seeds(catalog["projects"]!, null, seeds);
            }
            Generate(root, generated, sdk, request.String("nuget-packages"), report["nuget"]!["locked"]!, entry, tests, declaredLayout, directCheckout ? source : null, lockedRestore, packageActions);
            var watched = (directCheckout ? new[] { seeds } : new[] { inputs, seeds }).Concat(tests is null || directCheckout ? [] : new[] { Path.Combine(generated, "test-data") }).ToDictionary(p => p, p => FileTree.Snapshot(p));
            var watchedFiles = Directory.GetFiles(generated).ToDictionary(p => p, p => Json.Sha(File.ReadAllBytes(p)));
            var command = new List<string> { "--nosystem_rc", "--nohome_rc", "--noworkspace_rc", "--output_base=" + Path.Combine(state, "b"), "--output_user_root=" + Path.Combine(state, "u"), operation, "//:" + operation, "--incompatible_autoload_externally=", "--lockfile_mode=error", "--jobs=2", "--spawn_strategy=darwin-sandbox", "--strategy=MsbuildDiscover=local", "--strategy=MsbuildLockedRestore=local", "--execution_log_json_file=" + Path.Combine(output, "execution.json"), "--noshow_progress", "--color=no", "--curses=no" };
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
                command.AddRange(["--remote_cache=" + gate.Url, "--remote_upload_local_results=" + (request["bazel-remote-upload"]?.GetValue<bool>() == true ? "true" : "false"), "--remote_cache_async=false", "--remote_verify_downloads=true", "--remote_download_outputs=" + (projectActions ? "toplevel" : "all")]);
            }
            else if (request["bazel-remote-upload"]?.GetValue<bool>() == true) throw new InvalidDataException("Upload requires cache endpoint");
            var discoveryEvents = Array.Empty<JsonNode>();
            if (projectActions)
            {
                var layoutPath = Path.Combine(state, "project-layout.json");
                var saved = File.Exists(layoutPath) ? Json.Read(layoutPath) : null;
                var knownBodies = (declaredLayout ?? saved?["graph"])?["projects"]?.AsObject().SelectMany(pair => pair.Value!.Array("sources")).Select(value => value!.GetValue<string>()).ToHashSet(StringComparer.Ordinal) ?? [];
                var structural = directCheckout ? (JsonObject)sourceIdentity.DeepClone() : FileTree.Snapshot(inputs);
                foreach (var (name, item) in structural)
                    if ((name.EndsWith(".cs", StringComparison.Ordinal) || knownBodies.Contains(name)) && !name.Contains("/obj/", StringComparison.Ordinal) && item!.String("kind") == "file") { item!.AsObject().Remove("sha256"); item.AsObject().Remove("size"); }
                var fingerprint = Json.Digest(new JsonObject { ["inputs"] = structural.DeepClone(), ["packages"] = report["nuget"]!["locked"]!.DeepClone(), ["worker"] = worker.DeepClone(), ["entry"] = entry });
                JsonNode layout;
                if (declaredLayout is not null) { layout = declaredLayout; report["layoutSource"] = "declared"; }
                else if (saved?["identity"]?.GetValue<string>() == fingerprint) { layout = saved["graph"]!; report["layoutSource"] = "local"; }
                else
                {
                    var log = Path.Combine(output, "discovery-execution.json");
                    var discoveryCommand = command.Select(argument => argument == operation ? "build" : argument == "//:" + operation ? "//:prepare" : argument.StartsWith("--execution_log_json_file=", StringComparison.Ordinal) ? "--execution_log_json_file=" + log : argument)
                        .Where(argument => !argument.StartsWith("--test_output=", StringComparison.Ordinal) && !argument.StartsWith("--cache_test_results=", StringComparison.Ordinal)).Append("--output_groups=discovery").ToList();
                    var discoveryCode = Measure("layout", () => NativeWorkflow.Execute(bazel, discoveryCommand, generated, Path.Combine(output, "discovery-bazel.log")));
                    if (discoveryCode != 0) { File.Copy(Path.Combine(output, "discovery-bazel.log"), Path.Combine(output, "bazel.log")); throw new InvalidDataException("Bazel graph discovery failed; see bazel.log"); }
                    discoveryEvents = NativeWorkflow.Events(File.ReadAllBytes(log)).ToArray();
                    layout = ProjectLayout.Capture(Json.Read(Path.Combine(generated, "bazel-bin/prepare.discovery/graph.json"))); report["layoutSource"] = "bootstrap";
                    foreach (var name in layout["projects"]!.AsObject().SelectMany(pair => pair.Value!.Array("sources")).Select(value => value!.GetValue<string>()))
                        if (structural[name] is JsonObject item) { item.Remove("sha256"); item.Remove("size"); }
                    fingerprint = Json.Digest(new JsonObject { ["inputs"] = structural.DeepClone(), ["packages"] = report["nuget"]!["locked"]!.DeepClone(), ["worker"] = worker.DeepClone(), ["entry"] = entry });
                    Json.Write(layoutPath, new JsonObject { ["identity"] = fingerprint, ["graph"] = layout.DeepClone() });
                }
                Json.Write(Path.Combine(output, "project-layout.json"), layout);
                if (declaredLayout is null) Generate(root, generated, sdk, request.String("nuget-packages"), report["nuget"]!["locked"]!, entry, tests, layout, directCheckout ? source : null, lockedRestore, packageActions);
                report["bazelInvocations"] = report["layoutSource"]!.GetValue<string>() == "bootstrap" ? 2 : 1;
                watchedFiles = Directory.GetFiles(generated).ToDictionary(path => path, path => Json.Sha(File.ReadAllBytes(path)));
                report["cacheProtocol"] = "bazel-project-actions";
            }
            var code = Measure("bazel", () => NativeWorkflow.Execute(bazel, command, generated, Path.Combine(output, "bazel.log"))); report["exitCode"] = code;
            var events = File.Exists(Path.Combine(output, "execution.json")) ? NativeWorkflow.Events(File.ReadAllBytes(Path.Combine(output, "execution.json"))).ToArray() : [];
            events = discoveryEvents.Concat(events).ToArray();
            foreach (var mnemonic in new[] { "MsbuildDiscover", "MsbuildBindSources", "MsbuildNativeCache", "MsbuildBindProject", "MsbuildCompileProject", "MsbuildComposeRuntime", "MsbuildValidateLayout", "MsbuildNormalizeRestore", "MsbuildLockedRestore", "NugetExtractPackage" })
            {
                var actions = events.Where(n => n["mnemonic"]?.GetValue<string>() == mnemonic).ToArray();
                var executed = actions.Where(n => n["cacheHit"]?.GetValue<bool>() != true).ToArray();
                if (mnemonic is not ("MsbuildDiscover" or "MsbuildLockedRestore") && executed.Any(n => n["runner"]?.GetValue<string>() != "darwin-sandbox")) throw new InvalidDataException("Native sandbox required");
                report[mnemonic] = new JsonObject { ["executed"] = executed.Length, ["remoteHits"] = actions.Count(n => n["cacheHit"]?.GetValue<bool>() == true && n["runner"]?.GetValue<string>() == "remote cache hit") };
            }
            if (code != 0) throw new InvalidDataException("Bazel action/test failed; see bazel.log");
            report["compiles"] = report["MsbuildNativeCache"]!["executed"]!.GetValue<int>() == 0 ? 0 : Json.Read(Path.Combine(generated, "bazel-bin/build.diagnostics/action.json"))["compiles"]!.DeepClone();
            if (projectActions)
            {
                var executed = events.Where(n => n["mnemonic"]?.GetValue<string>() == "MsbuildCompileProject" && n["cacheHit"]?.GetValue<bool>() != true).ToArray();
                report["compiles"] = executed.Length;
                foreach (var action in executed)
                {
                    var requestFile = action.Array("commandArgs").Last()!.GetValue<string>();
                    var actionRequest = Json.Read(Path.Combine(generated, "bazel-out", "darwin_arm64-fastbuild", "bin", Path.GetFileName(requestFile)));
                    var diagnostics = Path.Combine(generated, "bazel-bin", Path.GetFileName(actionRequest.String("diagnostics")), "action.json");
                    if (Json.Read(diagnostics)["compiles"]!.GetValue<int>() != 1) throw new InvalidDataException("Project action compiled more than its entry");
                }
            }
            if (operation == "test")
            {
                var testReport = Path.Combine(generated, "bazel-testlogs/test/test.outputs/report.json"); report["test"] = Json.Read(testReport);
                if (report["test"]!["passed"]?.GetValue<bool>() != true || report["test"]!["buildOrRestoreInvoked"]?.GetValue<bool>() != false) throw new InvalidDataException("Test acceptance failed");
            }
            var bundle = Host.Real(Path.Combine(generated, "bazel-bin/build.bundle"));
            var bundleCache = Path.Combine(bundle, "cache");
            string Content(string path) => Json.Digest(new JsonObject(FileTree.Files(path).Select(p => KeyValuePair.Create<string, JsonNode?>(Path.GetRelativePath(path, p), JsonValue.Create(Json.Sha(File.ReadAllBytes(p)))))));
            if (!projectActions && request["bazel-remote-upload"]?.GetValue<bool>() == true && Content(seeds) != Content(bundleCache))
                Measure("primeActionCache", () =>
                {
                    // Prime the complete seed variant only after the original build/test
                    // passed. Both action publications remain behind the same gate.
                    foreach (var (path, expected) in watched) FileTree.Verify(path, expected);
                    foreach (var (path, hash) in watchedFiles.Concat(controllerFiles)) if (Json.Sha(File.ReadAllBytes(path)) != hash) throw new InvalidDataException("Declared controller input changed");
                    var expectedCache = Content(bundleCache); var expectedApp = FileTree.Snapshot(Path.Combine(bundle, "app"));
                    FileTree.Remove(seeds); FileTree.Copy(bundleCache, seeds, preserveModes: false);
                    watched[seeds] = FileTree.Snapshot(seeds);
                    Generate(root, generated, sdk, request.String("nuget-packages"), report["nuget"]!["locked"]!, entry, tests);
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
                if (layoutPathInput is not null && FileTree.HashRegular(layoutPathInput).Digest != layoutDigest) throw new InvalidDataException("Declared project layout changed");
                foreach (var (path, expected) in watched.Concat(controllerOriginal)) FileTree.Verify(path, expected);
                foreach (var (path, hash) in watchedFiles.Concat(controllerFiles)) if (Json.Sha(File.ReadAllBytes(path)) != hash) throw new InvalidDataException("Declared controller input changed");
                return true;
            });
            Measure("validateBundles", () =>
            {
                if (projectActions)
                {
                    var metadata = Host.Real(Path.Combine(generated, "bazel-bin/build.metadata"));
                    var files = FileTree.Files(metadata).ToDictionary(path => Path.GetRelativePath(metadata, path), File.ReadAllBytes);
                    var app = Path.Combine(bundle, "app");
                    foreach (var path in FileTree.Files(app)) files.Add("artifacts/" + Path.GetRelativePath(app, path), File.ReadAllBytes(path));
                    RemoteCache.ValidateBundle(files);
                }
                else foreach (var folder in Directory.GetDirectories(bundleCache)) RemoteCache.ValidateBundle(FileTree.Files(folder).ToDictionary(p => Path.GetRelativePath(folder, p), File.ReadAllBytes));
                return true;
            });
            if (!projectActions) { FileTree.Remove(cache); FileTree.Copy(bundleCache, cache, preserveModes: false); }
            if (remote is not null) report["publishedSnapshot"] = remote.Publish(cache, null, null, worker);
            Measure("publishActionCache", () => { gate?.Publish(); return true; }); report["accepted"] = true;
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
    private static void Generate(string root, string generated, string sdk, string packageCache, JsonNode packages, string entry, JsonNode? tests, JsonNode? layout = null, string? checkout = null, bool lockedRestore = false, bool packageActions = false)
    {
        foreach (var name in new[] { "msbuild.bzl", "native_cache.bzl", "native_test.bzl", "preparation.bzl", "input_paths.bzl", "repositories.bzl", "project_actions.bzl", "restore_inputs.bzl", "nuget_package.bzl" }) Host.Copy(Path.Combine(root, "bazel", name), Path.Combine(generated, name));
        Host.Copy(Path.Combine(root, "bazel/native.MODULE.bazel.lock"), Path.Combine(generated, "MODULE.bazel.lock"));
        File.WriteAllText(Path.Combine(generated, "MODULE.bazel"), "module(name = \"native_msbuild_workflow\")\nbazel_dep(name = \"platforms\", version = \"0.0.11\")\nlocal_dotnet_sdk = use_repo_rule(\"//:msbuild.bzl\", \"local_dotnet_sdk\")\n" + Starlark.Call("local_dotnet_sdk", new JsonObject { ["name"] = "dotnet", ["path"] = sdk, ["include_runtime_closure"] = true }));
        File.AppendAllText(Path.Combine(generated, "MODULE.bazel"), "owned_tools = use_repo_rule(\"//:repositories.bzl\", \"owned_tools\")\nnuget_archives = use_repo_rule(\"//:repositories.bzl\", \"nuget_archives\")\n" + Starlark.Call("owned_tools", new JsonObject { ["name"] = "owned_tools", ["root"] = root }) + Starlark.Call("nuget_archives", new JsonObject { ["name"] = "nuget", ["cache"] = packageCache, ["packages"] = Json.Canonical(packages), ["policy"] = "@owned_tools//:tools/pilot-package-policy.json", ["archives_only"] = packageActions }));
        string PackageLabel(string package) => "nuget_" + Json.Sha(Encoding.UTF8.GetBytes(package));
        var packageFiles = packageActions ? Array.Empty<string>() : new[] { "@nuget//:files" };
        JsonArray Files(string directory) => Json.Strings(FileTree.Files(Path.Combine(generated, directory)).Select(p => Path.GetRelativePath(generated, p)));
        var inputRoot = checkout ?? Path.Combine(generated, "inputs");
        var names = FileTree.Files(inputRoot).Select(path => Path.GetRelativePath(inputRoot, path)).Where(path => !path.StartsWith(".nuget/packages/", StringComparison.Ordinal) && (!lockedRestore || !FileTree.RestoreMetadata(path))).ToArray();
        string InputLabel(string path) => checkout is null ? "inputs/" + path : "@checkout//:workspace/" + path;
        JsonArray Inputs()
        {
            var result = Json.Strings(names.Where(path => checkout is null || !FileTree.RestoreMetadata(path)).Select(InputLabel));
            if (checkout is not null) result.Add(":restore_inputs");
            foreach (var packageFile in packageFiles) result.Add(packageFile); return result;
        }
        var resourceBodies = layout is null ? Array.Empty<string>() : layout["projects"]!.AsObject().SelectMany(pair => pair.Value!.Array("sources")).Select(value => value!.GetValue<string>()).Where(NativePlan.ResourcePath).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
        var build = "load(\":preparation.bzl\", \"msbuild_prepare\")\nload(\":native_cache.bzl\", \"msbuild_native_cache\")\nload(\":native_test.bzl\", \"native_test\")\n";
        if (packageActions)
        {
            build = "load(\":nuget_package.bzl\", \"nuget_extract_package\", \"nuget_package_set\")\n" + build;
            var pins = Json.Read(Path.Combine(root, "tools/pilot-package-policy.json"));
            var labels = new List<string>();
            foreach (var (package, hash) in packages.AsObject().OrderBy(pair => pair.Key, StringComparer.Ordinal))
            {
                var parts = package.Split('/'); var name = PackageLabel(package); labels.Add(":" + name);
                build += Starlark.Call("nuget_extract_package", new JsonObject { ["name"] = name, ["package"] = package, ["archive"] = "@nuget//:packages/" + package + "/" + parts[0] + "." + parts[1] + ".nupkg", ["content_hash"] = hash!.DeepClone(), ["pin"] = pins[package] is { } pin ? Json.Canonical(pin) : "", ["runner"] = "@owned_tools//:tools/Preparation/bin/Release/net10.0/Preparation.dll", ["runner_support"] = Json.Strings(["@owned_tools//:files"]), ["runtime"] = "@dotnet//:files", ["dotnet"] = "@dotnet//:sdk/dotnet" });
            }
            build += Starlark.Call("nuget_package_set", new JsonObject { ["name"] = "nuget_packages", ["packages"] = Json.Strings(labels) });
        }
        if (checkout is not null)
        {
            File.AppendAllText(Path.Combine(generated, "MODULE.bazel"), "checkout_inputs = use_repo_rule(\"//:repositories.bzl\", \"checkout_inputs\")\n" + Starlark.Call("checkout_inputs", new JsonObject { ["name"] = "checkout", ["root"] = checkout, ["files"] = Json.Strings(names) }));
            build = "load(\":restore_inputs.bzl\", \"msbuild_normalize_restore\", \"msbuild_locked_restore\")\n" + build;
            if (lockedRestore)
            {
                var configs = names.Where(name => !name.Contains('/') && name.Equals("NuGet.Config", StringComparison.OrdinalIgnoreCase)).ToArray();
                if (configs.Length != 1) throw new InvalidDataException("Locked restore requires one root NuGet.Config");
                build += Starlark.Call("msbuild_locked_restore", new JsonObject { ["resource_bodies"] = Json.Strings(resourceBodies), ["package_set"] = packageActions ? ":nuget_packages" : null, ["name"] = "restore_inputs", ["srcs"] = Json.Strings(names.Select(InputLabel).Concat(packageFiles)), ["project"] = entry, ["projects"] = Json.Strings(layout!["projects"]!.AsObject().Select(pair => pair.Key)), ["config"] = configs[0], ["runtime_manifest"] = "@dotnet//:runtime-roots.json", ["runner"] = "@owned_tools//:tools/Preparation/bin/Release/net10.0/Preparation.dll", ["controller"] = Json.Strings(["@owned_tools//:files"]), ["sdk"] = "@dotnet//:files", ["dotnet"] = "@dotnet//:sdk/dotnet" });
            }
            else
                build += Starlark.Call("msbuild_normalize_restore", new JsonObject { ["name"] = "restore_inputs", ["srcs"] = Json.Strings(names.Where(FileTree.RestoreMetadata).Select(InputLabel)), ["workspace"] = checkout, ["cache"] = packageCache, ["runner"] = "@owned_tools//:tools/Preparation/bin/Release/net10.0/Preparation.dll", ["controller"] = Json.Strings(["@owned_tools//:files"]), ["sdk"] = "@dotnet//:files", ["dotnet"] = "@dotnet//:sdk/dotnet" });
        }
        if (layout is not null) Json.Write(Path.Combine(generated, "project-layout.json"), layout);
        build += Starlark.Call("msbuild_prepare", new JsonObject { ["resource_bodies"] = Json.Strings(resourceBodies), ["projects"] = layout is null ? new JsonArray() : Json.Strings(layout["projects"]!.AsObject().Select(pair => pair.Key)), ["package_set"] = packageActions ? ":nuget_packages" : null, ["layout"] = layout is null ? null : "project-layout.json", ["name"] = "prepare", ["project"] = entry, ["srcs"] = Inputs(), ["controller"] = Json.Strings(["@owned_tools//:files"]), ["runner"] = "@owned_tools//:tools/Preparation/bin/Release/net10.0/Preparation.dll", ["host"] = "host.json", ["runtime_manifest"] = "@dotnet//:runtime-roots.json", ["sdk"] = "@dotnet//:files", ["dotnet"] = "@dotnet//:sdk/dotnet" });
        if (layout is null)
            build += Starlark.Call("msbuild_native_cache", new JsonObject { ["name"] = "build", ["project"] = entry, ["prepared_plan"] = ":prepare", ["direct_inputs"] = Inputs(), ["seeds"] = Files("seeds"), ["runner"] = "@owned_tools//:tools/NativeProjectCache/bin/Release/net10.0/NativeProjectCache.dll", ["runner_support"] = Json.Strings(["@owned_tools//:files"]), ["sdk"] = "@dotnet//:files", ["dotnet"] = "@dotnet//:sdk/dotnet" });
        else
        {
            build = "load(\":project_actions.bzl\", \"msbuild_compile_project\", \"msbuild_compose_runtime\")\n" + build;
            var nodes = layout["projects"]!.AsObject();
            string Label(string project) => "project_" + Json.Sha(Encoding.UTF8.GetBytes(project));
            var bodies = nodes.SelectMany(pair => pair.Value!.Array("sources")).Select(input => InputLabel(input!.GetValue<string>())).ToHashSet(StringComparer.Ordinal);
            var structural = Inputs().Select(value => value!.GetValue<string>()).Where(path => !bodies.Contains(path) && !path.EndsWith(".cs", StringComparison.Ordinal));
            build += Starlark.Call("filegroup", new JsonObject { ["name"] = "project_structural_inputs", ["srcs"] = Json.Strings(structural) });
            foreach (var (project, node) in nodes)
            {
                var sources = node!.Array("sources").Select(input => InputLabel(input!.GetValue<string>()));
                var projectStructural = node!["structural"] is JsonArray ownedInputs
                    ? Json.Strings(ownedInputs.Select(value => InputLabel(value!.GetValue<string>())).Concat(names.Where(name => name is "global.json" or "NuGet.Config" or "NuGet.config" or "Directory.Build.props" or "Directory.Build.targets").Select(InputLabel)).Concat(packageFiles).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal))
                    : Json.Strings([":project_structural_inputs"]);
                var projectPackages = packageActions ? ":nuget_packages" : null;
                if (packageActions && node!["packages"] is JsonArray selectedPackages)
                {
                    var selected = selectedPackages.Select(value => value!.GetValue<string>()).ToArray();
                    if (selected.Any(package => !packages.AsObject().ContainsKey(package))) throw new InvalidDataException("Project layout contains an unlocked package");
                    var packageSet = Label(project) + "_packages";
                    build += Starlark.Call("nuget_package_set", new JsonObject { ["name"] = packageSet, ["packages"] = Json.Strings(selected.Select(package => ":" + PackageLabel(package))) });
                    projectPackages = ":" + packageSet;
                }
                build += Starlark.Call("msbuild_compile_project", new JsonObject { ["package_set"] = projectPackages, ["name"] = Label(project), ["project"] = project, ["project_dependencies"] = node!["dependencies"]!.DeepClone(), ["dependencies"] = Json.Strings(node.Array("dependencies").Select(d => ":" + Label(d!.GetValue<string>()))), ["discovery"] = ":prepare", ["sources"] = Json.Strings(sources), ["structural"] = projectStructural, ["preparation"] = "@owned_tools//:tools/Preparation/bin/Release/net10.0/Preparation.dll", ["runner"] = "@owned_tools//:tools/NativeProjectCache/bin/Release/net10.0/NativeProjectCache.dll", ["runner_support"] = Json.Strings(["@owned_tools//:files"]), ["sdk"] = "@dotnet//:files", ["dotnet"] = "@dotnet//:sdk/dotnet" });
            }
            build += Starlark.Call("msbuild_compose_runtime", new JsonObject { ["name"] = "build", ["project"] = entry, ["entry"] = ":" + Label(entry), ["runner"] = "@owned_tools//:tools/NativeProjectCache/bin/Release/net10.0/NativeProjectCache.dll", ["runner_support"] = Json.Strings(["@owned_tools//:files"]), ["sdk"] = "@dotnet//:files", ["dotnet"] = "@dotnet//:sdk/dotnet" });
        }
        if (tests is not null)
        {
            var data = new JsonArray(); var hashes = new JsonObject(); var testData = Path.Combine(generated, "test-data"); FileTree.Remove(testData); Directory.CreateDirectory(testData);
            foreach (var item in tests.Array("data"))
            {
                var name = Host.Safe(item!.GetValue<string>()); var bytes = FileTree.ReadRegular(Path.Combine(inputRoot, name));
                if (checkout is null) { var path = Path.Combine(testData, name); Directory.CreateDirectory(Path.GetDirectoryName(path)!); File.WriteAllBytes(path, bytes); data.Add("test-data/" + name); }
                else data.Add(InputLabel(name));
                hashes[name] = Json.Sha(bytes);
            }
            build += Starlark.Call("native_test", new JsonObject { ["name"] = "test", ["subject"] = ":build", ["project"] = entry, ["prepared_plan"] = ":prepare", ["global_properties"] = new JsonObject { ["configuration"] = "Release", ["targetframework"] = "net10.0" }, ["runtime_directory"] = Path.Combine(Path.GetDirectoryName(entry)!, "bin/Release/net10.0"), ["assembly"] = Path.GetFileNameWithoutExtension(entry) + ".dll", ["data"] = data, ["data_hashes"] = hashes, ["expected_tests"] = tests["expectedTests"]!.DeepClone(), ["runner"] = "@owned_tools//:tools/TestRunner/bin/Release/net10.0/TestRunner.dll", ["runner_support"] = Json.Strings(["@owned_tools//:files"]), ["host_identity"] = "host.json", ["sdk"] = "@dotnet//:files", ["dotnet"] = "@dotnet//:sdk/dotnet", ["size"] = "small", ["timeout"] = "moderate" });
        }
        File.WriteAllText(Path.Combine(generated, "BUILD.bazel"), build);
    }
}
