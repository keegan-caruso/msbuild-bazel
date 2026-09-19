using System.Diagnostics;
using System.IO.Compression;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

internal static class NativeWorkflow
{
    private static readonly string[] Tools = ["GraphExport", "EvaluationProbe", "ReplayPlugin", "ActionRunner", "NativeProjectCache", "TestRunner"];
    private static readonly string[] Imports = OperatingSystem.IsLinux() ? [] : ["/nix/store/dfhdbgnvv0jm1ld0hrzfaklgigvl7bzp-extra.targets", "/nix/store/hm53cqanyh9f8dl3bij21iyhvk1mlb30-sign-apphost.proj"];
    private const string Owner = "dotnet-native-workflow-v1";
    public static JsonNode Arguments(string[] args)
    {
        var result = new JsonObject { ["schemaVersion"] = 1, ["operation"] = "build" };
        var flags = new HashSet<string>(["reuse", "independent-workers", "incremental-sources", "trust-system-nix-store", "bootstrap", "force-tests", "bazel-disable-repository-downloads", "bazel-remote-upload", "integrity-profile"], StringComparer.Ordinal);
        for (var i = 0; i < args.Length; i++)
        {
            if (!args[i].StartsWith("--", StringComparison.Ordinal)) throw new ArgumentException("Expected named argument");
            var name = args[i][2..]; if (result.ContainsKey(name) && name != "operation") throw new ArgumentException("Duplicate argument");
            if (flags.Contains(name)) result[name] = true;
            else { if (++i == args.Length) throw new ArgumentException("Missing argument value"); result[name] = args[i]; }
        }
        if (result["tests"] is { } tests) result["tests"] = Json.Read(tests.GetValue<string>());
        return result;
    }
    private static string Tool(string root, string name) => Path.Combine(root, "tools", name, "bin/Release/net10.0", name + ".dll");
    private static void Disjoint(string a, string b) { if (Host.Within(a, b) || Host.Within(b, a)) throw new InvalidDataException("Paths must be disjoint: " + a + " and " + b); }
    public static JsonNode Run(JsonNode request, ProtectedStore? sessionStore = null)
    {
        var allowed = new HashSet<string>(["schemaVersion", "repository", "sdkRoot", "bazel", "workspace", "state", "entry", "output", "operation", "reuse", "independent-workers", "incremental-sources", "trust-system-nix-store", "bootstrap", "force-tests", "tests", "nuget-packages", "remote-endpoint", "remote-snapshot", "bazel-install-cache", "bazel-repository-cache", "bazel-disable-repository-downloads", "bazel-remote-cache", "bazel-remote-upload", "integrity-profile"], StringComparer.Ordinal);
        if (request["schemaVersion"]?.GetValue<int>() != 1 || request.AsObject().Any(p => !allowed.Contains(p.Key))) throw new InvalidDataException("Invalid workflow request");
        var root = Host.Real(request["repository"]?.GetValue<string>() ?? Environment.GetEnvironmentVariable("RULES_MSBUILD_REPOSITORY") ?? throw new ArgumentException("repository required"));
        if (sessionStore is not null && Host.Real(typeof(NativeWorkflow).Assembly.Location) != Host.Real(Tool(root, "Preparation"))) throw new InvalidDataException("Controller session repository differs from loaded controller");
        var sdk = Host.Real(request["sdkRoot"]?.GetValue<string>() ?? Environment.GetEnvironmentVariable("RULES_MSBUILD_DOTNET_ROOT") ?? Path.Combine(root, ".tools/dotnet"));
        if (sessionStore is not null && Host.Real(Environment.ProcessPath ?? throw new InvalidDataException("Unknown controller host")) != Host.Real(Path.Combine(sdk, "dotnet"))) throw new InvalidDataException("Controller session SDK differs from loaded host; restart with the selected SDK");
        var bazel = request["bazel"]?.GetValue<string>() ?? Environment.GetEnvironmentVariable("RULES_MSBUILD_BAZEL") ?? Path.Combine(root, ".tools/bin/bazel");
        var source = Host.Real(request.String("workspace")); var state = Host.Real(request.String("state")); var output = Host.Real(request.String("output")); var entry = Host.Safe(request.String("entry"));
        Disjoint(source, root); Disjoint(source, state); Disjoint(state, root); foreach (var path in new[] { source, state, root }) Disjoint(output, path);
        var operation = request.String("operation"); var tests = request["tests"];
        var independent = request["independent-workers"]?.GetValue<bool>() == true;
        var actionEndpoint = request["bazel-remote-cache"] is { } actionOption ? ActionCache.Endpoint(actionOption.GetValue<string>()) : null;
        var actionUpload = request["bazel-remote-upload"]?.GetValue<bool>() == true;
        if (actionUpload && actionEndpoint is null) throw new InvalidDataException("Action cache upload requires an endpoint");
        if (actionEndpoint is not null && !independent) throw new InvalidDataException("Action cache requires independent-workers identity");
        ActionCache? actionCache = null;
        var publishActionCache = true;
        if (operation is not ("build" or "test") || operation == "test" && tests is null) throw new InvalidDataException("Test requires explicit test declaration");
        if (!OperatingSystem.IsMacOS() && !OperatingSystem.IsLinux()) throw new PlatformNotSupportedException("Native sandbox workflow requires macOS or Linux");
        if (OperatingSystem.IsLinux()) LinuxPlatform.Require(sdk);
        var sandbox = OperatingSystem.IsLinux() ? "linux-sandbox" : "darwin-sandbox";
        if (Path.Exists(output)) throw new IOException("Report output exists"); Directory.CreateDirectory(output);
        using var lease = Host.Lock(Path.Combine(state, "lease"));
        var owner = Path.Combine(state, "owner.json");
        if (!File.Exists(owner))
        {
            if (Directory.GetFileSystemEntries(state).Any(p => Path.GetFileName(p) != "lease")) throw new InvalidDataException("State is not owned by this workflow");
            FileTree.Atomic(owner, new JsonObject { ["policy"] = Owner });
        }
        if (Json.Read(owner).String("policy") != Owner) throw new InvalidDataException("State policy mismatch");
        var timer = Stopwatch.StartNew(); var phases = new JsonObject(); var report = new JsonObject { ["accepted"] = false, ["operation"] = operation, ["phases"] = phases };
        T Measure<T>(string name, Func<T> action) { var watch = Stopwatch.StartNew(); try { return action(); } finally { phases[name] = watch.Elapsed.TotalSeconds; } }
        var store = request["trust-system-nix-store"]?.GetValue<bool>() == true ? sessionStore ?? new ProtectedStore() : null;
        var storeHits = store?.Hits ?? 0; var storeScans = store?.FullScans ?? 0;
        var profiling = request["integrity-profile"]?.GetValue<bool>() == true;
        var integrity = new JsonArray();
        if (profiling) report["integrityProfile"] = integrity;
        T Detail<T>(string phase, string category, string path, Func<T> action)
        {
            if (!profiling) return action();
            var clock = Stopwatch.StartNew();
            try { return action(); }
            finally { integrity.Add(new JsonObject { ["phase"] = phase, ["category"] = category, ["path"] = path, ["seconds"] = clock.Elapsed.TotalSeconds }); }
        }
        JsonObject Scan(string phase, string path, bool links) => links && store is not null ? store.Snapshot(path, () => FullScan(phase, path, links)) : FullScan(phase, path, links);
        JsonObject FullScan(string phase, string path, bool links)
        {
            if (!profiling) return FileTree.Snapshot(path, links);
            var detail = new IntegrityProfile(); var clock = Stopwatch.StartNew();
            var snapshot = FileTree.Snapshot(path, links, detail);
            var item = detail.Report(); item["phase"] = phase; item["category"] = "scan"; item["path"] = path; item["seconds"] = clock.Elapsed.TotalSeconds;
            integrity.Add(item); return snapshot;
        }
        var temporary = Path.Combine(state, "pending"); FileTree.Remove(temporary); Directory.CreateDirectory(temporary);
        using var remote = request["remote-endpoint"] is { } endpoint ? new RemoteCache(endpoint.GetValue<string>()) : null;
        if (request["remote-snapshot"] is { } selected) { RemoteCache.Digest(selected.GetValue<string>()); if (remote is null) throw new InvalidDataException("Snapshot requires endpoint"); }
        try
        {
            if (request["bootstrap"]?.GetValue<bool>() == true)
            {
                using var buildLease = Host.Lock(Path.Combine(root, "artifacts/graph-preparation.lock"));
                foreach (var name in Tools) Host.Run(Path.Combine(sdk, "dotnet"), ["build", Path.Combine(root, "tools", name), "-c", "Release", "--nologo"], root, Host.SdkEnvironment(sdk, "10.0.400"));
            }
            var bound = Tools.ToDictionary(n => n, n => Tool(root, n), StringComparer.Ordinal);
            foreach (var path in bound.Values) if (!File.Exists(path)) throw new InvalidDataException("Missing built tool; use --bootstrap");
            var watched = new Dictionary<string, JsonObject>(StringComparer.Ordinal);
            var watchedFiles = new Dictionary<string, string>(StringComparer.Ordinal);
            JsonObject? worker = null;
            string? controllerClosure = null;
            var toolchain = Measure("identity", () =>
            {
                foreach (var name in Tools.Append("Preparation")) { var folder = Path.Combine(root, "tools", name, "bin/Release/net10.0"); watched[folder] = Scan("identity", folder, false); }
                watched[Path.Combine(root, "bazel")] = Scan("identity", Path.Combine(root, "bazel"), false);
                var runtime = new JsonObject();
                var runtimeRoots = sdk.StartsWith("/nix/store/", StringComparison.Ordinal)
                    ? Detail("identity", "closureQuery", sdk, () => Host.Run("/nix/var/nix/profiles/default/bin/nix-store", ["-qR", Path.GetDirectoryName(Path.GetDirectoryName(sdk))!], root)).Split('\n', StringSplitOptions.RemoveEmptyEntries)
                    : OperatingSystem.IsLinux() ? new[] { sdk }.Concat(LinuxPlatform.Libraries).ToArray() : new[] { sdk };
                foreach (var path in runtimeRoots.Order(StringComparer.Ordinal)) { watched[path] = Scan("identity", path, true); runtime[path] = Detail("identity", "manifestDigest", path, () => Json.Digest(watched[path])); }
                var identity = new JsonObject { ["policy"] = Owner, ["platform"] = RuntimeInformation.OSDescription, ["machine"] = RuntimeInformation.OSArchitecture.ToString(), ["sdk"] = Json.Digest(runtime) };
                foreach (var (path, value) in watched.Where(p => Host.Within(p.Key, root))) identity[Path.GetRelativePath(root, path)] = Json.Digest(value);
                foreach (var path in Imports) { watchedFiles[path] = Json.Sha(File.ReadAllBytes(path)); identity[path] = watchedFiles[path]; }
                foreach (var path in new[] { "pilot-package-policy.json", "discovery-test-packages.json", "discovery-sdk-imports.json", "orchard-discovery-policy.json" }) { var full = Path.Combine(root, "tools", path); watchedFiles[full] = Json.Sha(File.ReadAllBytes(full)); identity[path] = watchedFiles[full]; }
                controllerClosure = Json.Digest(identity);
                worker = Detail("identity", "workerCapture", bazel, () => WorkerIdentity.Capture(controllerClosure, bazel, root, independent));
                report["worker"] = worker.DeepClone();
                return WorkerIdentity.Digest(worker);
            });
            var cacheRoot = Host.Real(request["nuget-packages"]?.GetValue<string>() ?? Environment.GetEnvironmentVariable("NUGET_PACKAGES") ?? Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".nuget/packages"));
            var workspace = Path.Combine(state, "workspace"); report["nuget"] = Measure("nuget", () => NuGetInputs.Stage(source, workspace, cacheRoot));
            var sourceIdentity = FileTree.Snapshot(workspace);
            JsonNode? snapshot = null;
            if (remote is not null)
            {
                report["remote"] = new JsonObject();
                if (request["remote-snapshot"] is { } hash)
                    try { snapshot = Measure("remoteSnapshot", () => remote.Snapshot(hash.GetValue<string>(), worker)); } catch (Exception error) { report["remote"]!["snapshotMiss"] = error.Message; }
            }
            var plan = Path.Combine(temporary, "plan"); var localPlan = Path.Combine(state, "preparation"); JsonNode? receipt = null; Discovery? discovery = null; var reused = false; var refreshed = false;
            Measure("prepare", () =>
            {
                var discoveryDirectory = Path.Combine(state, "discovery"); FileTree.Remove(discoveryDirectory);
                try { discovery = new Discovery(root, sdk, workspace, discoveryDirectory, toolchain, watched); } catch (InvalidDataException error) { report["preparationMiss"] = error.Message; }
                if (request["reuse"]?.GetValue<bool>() == true || remote is not null)
                {
                    if (File.Exists(Path.Combine(localPlan, "receipt.json")))
                        try
                        {
                            receipt = Json.Read(Path.Combine(localPlan, "receipt.json")); FileTree.Copy(Path.Combine(localPlan, "payload"), plan);
                            if (Json.Digest(FileTree.Snapshot(plan)) != receipt.String("payload")) throw new InvalidDataException("Local preparation changed");
                        }
                        catch (Exception error) { report["preparationMiss"] = error.Message; receipt = null; FileTree.Remove(plan); }
                    if (receipt is null && snapshot?["preparation"] is { } hash)
                        try { receipt = remote!.Preparation(hash.GetValue<string>(), plan, [cacheRoot, Path.Combine(workspace, ".nuget/packages")]); }
                        catch (Exception error) { report["preparationMiss"] = error.Message; receipt = null; FileTree.Remove(plan); }
                    try
                    {
                        if (receipt is not null && discovery is not null && receipt.String("entry") == entry && discovery.Rebase(receipt))
                        {
                            reused = JsonNode.DeepEquals(receipt["inputs"], discovery.WorkspaceIdentity);
                            if (!reused && (request["incremental-sources"]?.GetValue<bool>() == true || remote is not null)) refreshed = NativePlan.Refresh(plan, workspace, receipt["inputs"]!, discovery.WorkspaceIdentity) is not null;
                        }
                    }
                    catch (Exception error) when (error is InvalidDataException or IOException or InvalidOperationException or ArgumentException or NullReferenceException or KeyNotFoundException or JsonException)
                    {
                        report["preparationMiss"] = error.Message; reused = false; refreshed = false;
                    }
                }
                if (!reused && !refreshed)
                {
                    FileTree.Remove(plan); receipt = null; JsonNode? graph = null;
                    if (discovery is not null)
                        try { graph = discovery.Capture(entry); }
                        catch (InvalidDataException error) { report["preparationMiss"] = error.Message; discovery = null; }
                    if (graph is null)
                    {
                        var export = Path.Combine(temporary, "export.json"); var graphPath = Path.Combine(temporary, "graph.json");
                        Json.Write(export, new JsonObject { ["schemaVersion"] = 1, ["workspace"] = workspace, ["dotnetRoot"] = sdk, ["sdkVersion"] = "10.0.400", ["packageRoot"] = Path.Combine(workspace, ".nuget/packages"), ["entryPoints"] = new JsonArray(new JsonObject { ["project"] = entry, ["globalProperties"] = new JsonObject { ["Configuration"] = "Release", ["TargetFramework"] = "net10.0" } }), ["output"] = graphPath });
                        var exportEnvironment = Host.SdkEnvironment(sdk, "10.0.400"); exportEnvironment["MSBuildEnableWorkloadResolver"] = "false";
                        Host.Run(Path.Combine(sdk, "dotnet"), [bound["GraphExport"], "--request", export], workspace, exportEnvironment); graph = Json.Read(graphPath);
                    }
                    NativePlan.Qualify(graph); var path = Path.Combine(temporary, "graph.json"); Json.Write(path, graph); var prepared = Path.Combine(temporary, "validated");
                    GraphPreparation.Run(new JsonObject { ["schemaVersion"] = 1, ["repository"] = root, ["workspace"] = workspace, ["manifest"] = path, ["output"] = prepared, ["sdkRoot"] = sdk, ["sdkVersion"] = "10.0.400" }, bound, discovery is null ? null : () => discovery.Export(entry));
                    NativePlan.Materialize(prepared, graph, plan, toolchain, repository: root);
                }
                receipt = discovery?.Receipt(entry, plan);
                return true;
            });
            if (discovery is null) sourceIdentity = FileTree.Snapshot(workspace);
            report["preparation"] = new JsonObject { ["reused"] = reused || refreshed, ["discoveryExecuted"] = !reused && !refreshed, ["sourceContentUpdate"] = refreshed };
            var payloadIdentity = FileTree.Snapshot(plan);
            var cache = Path.Combine(state, "cache"); var seeds = Path.Combine(temporary, "seeds"); Directory.CreateDirectory(seeds);
            if (Directory.Exists(cache))
                try { FileTree.Copy(cache, seeds, preserveModes: false); }
                catch (Exception error) when (error is IOException or InvalidDataException) { report["cacheRejection"] = error.Message; FileTree.Remove(seeds); Directory.CreateDirectory(seeds); }
            report["workerCacheEligible"] = independent && discovery is not null;
            if (snapshot is not null && (!independent || discovery is not null)) Measure("remoteSeeds", () => { remote!.Seeds(snapshot["projects"]!, Json.Read(Path.Combine(plan, "manifest.json")), seeds); return true; });
            var generated = Path.Combine(state, "g");
            Measure("stage", () => { new NativeWorkspace(generated).Generate(root, sdk, plan, workspace, tests, seeds, Imports); return true; });
            var execution = Path.Combine(output, "execution.json");
            var command = new List<string> { "--nosystem_rc", "--nohome_rc", "--noworkspace_rc", "--output_base=" + Path.Combine(state, "b"), "--output_user_root=" + Path.Combine(state, "u"), operation, "//:" + operation, "--incompatible_autoload_externally=", "--lockfile_mode=error", "--jobs=2", "--spawn_strategy=" + sandbox, "--strategy=MsbuildNativeCache=" + sandbox, "--execution_log_json_file=" + execution, "--noshow_progress", "--color=no", "--curses=no" };
            if (request["bazel-install-cache"] is { } installCache)
            {
                // Share only the extracted, binary-keyed Bazel distribution. The
                // server, action cache and repository state remain per workspace.
                var installRoot = Host.Real(installCache.GetValue<string>());
                var installBase = Host.Real(Path.Combine(installRoot, worker!["systemTools"]!.String("bazel")));
                foreach (var path in new[] { source, state, root, output, sdk }) { Disjoint(installRoot, path); Disjoint(installBase, path); }
                command.Insert(3, "--install_base=" + installBase);
                report["bazelInstallBase"] = installBase;
            }
            if (request["bazel-repository-cache"] is { } repositoryCache)
            {
                var cachePath = Host.Real(repositoryCache.GetValue<string>());
                foreach (var path in new[] { source, state, root, output, sdk }) Disjoint(cachePath, path);
                if (request["bazel-install-cache"] is { } install) Disjoint(cachePath, Host.Real(install.GetValue<string>()));
                command.Add("--repository_cache=" + cachePath);
                report["bazelRepositoryCache"] = cachePath;
            }
            if (actionEndpoint is not null)
            {
                if (discovery is null) throw new InvalidDataException("Action cache requires qualified discovery");
                actionCache = new ActionCache(actionEndpoint, Path.Combine(temporary, "action-cache"), actionUpload);
                command.AddRange(["--remote_cache=" + actionCache.Url, "--remote_upload_local_results=" + (actionUpload ? "true" : "false"), "--remote_cache_async=false", "--remote_verify_downloads=true", "--remote_download_outputs=all"]);
            }
            if (request["bazel-disable-repository-downloads"]?.GetValue<bool>() == true) command.Add("--repository_disable_download");
            if (operation == "test") command.AddRange(["--test_output=errors", "--cache_test_results=" + (request["force-tests"]?.GetValue<bool>() == true ? "no" : "yes")]);
            var exitCode = Measure("bazel", () => Execute(bazel, command, generated, Path.Combine(output, "bazel.log"))); report["exitCode"] = exitCode;
            var actions = File.Exists(execution) ? Events(File.ReadAllBytes(execution)).ToArray() : [];
            var builds = actions.Where(n => n["mnemonic"]?.GetValue<string>() == "MsbuildNativeCache" && n["cacheHit"]?.GetValue<bool>() != true).ToArray();
            if (builds.Any(n => n["runner"]?.GetValue<string>() != sandbox)) throw new InvalidDataException("Native sandbox required");
            report["remoteBuildHits"] = actions.Count(n => n["mnemonic"]?.GetValue<string>() == "MsbuildNativeCache" && n["cacheHit"]?.GetValue<bool>() == true && n["runner"]?.GetValue<string>() == "remote cache hit");
            report["buildActions"] = builds.Length; report["testActions"] = actions.Count(n => n["mnemonic"]?.GetValue<string>() == "TestRunner" && n["cacheHit"]?.GetValue<bool>() != true);
            report["compiles"] = builds.Length == 0 ? 0 : Json.Read(Path.Combine(generated, "bazel-bin/build.diagnostics/action.json"))["compiles"]!.DeepClone();
            if (exitCode != 0) throw new InvalidDataException("Bazel failed; see bazel.log");
            if (tests is not null && operation == "test")
            {
                var testOutput = Path.Combine(generated, "bazel-testlogs/test/test.outputs");
                if (File.Exists(Path.Combine(testOutput, "outputs.zip"))) { using var archive = ZipFile.OpenRead(Path.Combine(testOutput, "outputs.zip")); using var stream = archive.GetEntry("report.json")!.Open(); report["test"] = JsonNode.Parse(stream); }
                else report["test"] = Json.Read(Path.Combine(testOutput, "report.json"));
                if (report["test"]!["passed"]?.GetValue<bool>() != true || report["test"]!["buildOrRestoreInvoked"]?.GetValue<bool>() != false) throw new InvalidDataException("Test acceptance failed");
            }
            var app = Path.Combine(generated, "bazel-bin/build.bundle/app"); var runtime = new JsonObject(); foreach (var file in FileTree.Files(app)) runtime[Path.GetRelativePath(app, file)] = Json.Sha(File.ReadAllBytes(file)); report["runtimeHashes"] = runtime;
            var stagedCache = Path.Combine(temporary, "cache"); FileTree.Copy(Host.Real(Path.Combine(generated, "bazel-bin/build.bundle/cache")), stagedCache, preserveModes: false);
            foreach (var folder in Directory.GetDirectories(stagedCache)) RemoteCache.ValidateBundle(FileTree.Files(folder).ToDictionary(p => Path.GetRelativePath(folder, p), File.ReadAllBytes, StringComparer.Ordinal));
            if (actionUpload && !JsonNode.DeepEquals(CacheContent(Path.Combine(generated, "seeds")), CacheContent(stagedCache)))
                Measure("primeActionCache", () =>
                {
                    var prime = new JsonObject { ["accepted"] = false }; report["cachePrime"] = prime;
                    var bundle = Host.Real(Path.Combine(generated, "bazel-bin/build.bundle"));
                    var diagnostics = Host.Real(Path.Combine(generated, "bazel-bin/build.diagnostics"));
                    var backup = Path.Combine(temporary, "primary-bundle"); var backupDiagnostics = Path.Combine(temporary, "primary-diagnostics");
                    FileTree.Copy(bundle, backup); FileTree.Copy(diagnostics, backupDiagnostics);
                    var expectedApp = FileTree.Snapshot(app);
                    try
                    {
                        new NativeWorkspace(generated).Generate(root, sdk, plan, workspace, tests, stagedCache, Imports);
                        var primeLog = Path.Combine(output, "prime-execution.json");
                        var primeCommand = command.Select(argument => argument == operation ? "build" : argument == "//:" + operation ? "//:build" : argument.StartsWith("--execution_log_json_file=", StringComparison.Ordinal) ? "--execution_log_json_file=" + primeLog : argument)
                            .Where(argument => !argument.StartsWith("--test_output=", StringComparison.Ordinal) && !argument.StartsWith("--cache_test_results=", StringComparison.Ordinal)).ToList();
                        var primeExit = Execute(bazel, primeCommand, generated, Path.Combine(output, "prime-bazel.log"));
                        if (primeExit != 0) throw new InvalidDataException("Seeded cache priming failed; see prime-bazel.log");
                        var primeActions = Events(File.ReadAllBytes(primeLog)).Where(n => n["mnemonic"]?.GetValue<string>() == "MsbuildNativeCache").ToArray();
                        var primeBuilds = primeActions.Where(n => n["cacheHit"]?.GetValue<bool>() != true).ToArray();
                        if (primeBuilds.Any(n => n["runner"]?.GetValue<string>() != sandbox)) throw new InvalidDataException("Priming requires native sandbox");
                        var primeCompiles = primeBuilds.Length == 0 ? 0 : Json.Read(Path.Combine(diagnostics, "action.json"))["compiles"]!.GetValue<int>();
                        if (primeCompiles != 0) throw new InvalidDataException("Seeded cache priming unexpectedly compiled");
                        FileTree.Verify(app, expectedApp);
                        if (!JsonNode.DeepEquals(CacheContent(Path.Combine(bundle, "cache")), CacheContent(stagedCache))) throw new InvalidDataException("Priming changed accepted project bundles");
                        prime["accepted"] = true; prime["buildActions"] = primeBuilds.Length; prime["compiles"] = primeCompiles;
                        prime["remoteBuildHits"] = primeActions.Count(n => n["cacheHit"]?.GetValue<bool>() == true && n["runner"]?.GetValue<string>() == "remote cache hit");
                    }
                    catch (Exception error)
                    {
                        // Warming is optional: retain the already tested build, and
                        // discard all staged outer writes if its validation failed.
                        publishActionCache = false; prime["error"] = error.Message; report["actionCachePublicationError"] = error.Message;
                        FileTree.Remove(bundle); FileTree.Copy(backup, bundle);
                        FileTree.Remove(diagnostics); FileTree.Copy(backupDiagnostics, diagnostics);
                    }
                    finally { FileTree.Remove(backup); FileTree.Remove(backupDiagnostics); }
                    return true;
                });
            Measure("leaseExit", () =>
            {
                Detail("leaseExit", "workerCapture", bazel, () => { WorkerIdentity.RequireCompatible(worker, WorkerIdentity.Capture(controllerClosure!, bazel, root, independent)); return true; });
                var verification = new FileTree.Verification(profiling || store is not null ? (path, links) => Scan("leaseExit", path, links) : null);
                discovery?.Verify(verification); verification.Verify(workspace, sourceIdentity); verification.Verify(plan, payloadIdentity); foreach (var (path, identity) in watched) verification.Verify(path, identity, !Host.Within(path, root));
                report["leaseVerification"] = new JsonObject { ["requests"] = verification.Requests, ["scans"] = verification.Scans };
                foreach (var (path, hash) in watchedFiles) if (Json.Sha(File.ReadAllBytes(path)) != hash) throw new InvalidDataException("Controller policy/import changed during consumption"); return true;
            });
            FileTree.Remove(cache); Directory.Move(stagedCache, cache);
            if (receipt is not null)
            {
                var publication = Path.Combine(temporary, "preparation"); Directory.CreateDirectory(publication); FileTree.Copy(plan, Path.Combine(publication, "payload")); Json.Write(Path.Combine(publication, "receipt.json"), receipt);
                FileTree.Remove(localPlan); Directory.Move(publication, localPlan);
            }
            if (remote is not null && independent && discovery is null)
                report["remote"]!["publicationSkipped"] = "Independent-worker cache requires qualified discovery";
            else if (remote is not null)
                Measure("remotePublish", () => { try { report["remote"]!["publishedSnapshot"] = remote.Publish(cache, receipt is null ? null : plan, receipt, worker); } catch (Exception error) { report["remote"]!["publicationError"] = error.Message; } return true; });
            if (actionCache is not null && publishActionCache)
                Measure("actionCachePublish", () =>
                {
                    try { actionCache.Publish(); }
                    catch (Exception error) when (error is IOException or InvalidDataException or HttpRequestException or TaskCanceledException) { report["actionCachePublicationError"] = error.Message; }
                    return true;
                });
            report["accepted"] = true;
        }
        finally
        {
            if (actionCache is not null) { actionCache.Dispose(); report["actionCache"] = actionCache.Statistics; }
            if (remote is not null) { report["remote"] ??= new JsonObject(); report["remote"]!["transport"] = remote.Statistics; }
            report["seconds"] = timer.Elapsed.TotalSeconds; if (store is not null) report["protectedStore"] = new JsonObject { ["policy"] = "trusted-system-nix-session-v1", ["hits"] = store.Hits - storeHits, ["fullScans"] = store.FullScans - storeScans, ["roots"] = store.Roots };
            Json.Write(Path.Combine(output, "report.json"), report); FileTree.Remove(temporary);
        }
        return report;
    }
    private static JsonObject CacheContent(string root)
    {
        if (!Directory.Exists(root)) return new JsonObject();
        var content = FileTree.Snapshot(root);
        foreach (var item in content) item.Value!.AsObject().Remove("mode");
        return content;
    }
    internal static int Execute(string executable, List<string> arguments, string cwd, string log)
    {
        const string prefix = "--execution_log_json_file=";
        var traceArgument = arguments.SingleOrDefault(argument => argument.StartsWith(prefix, StringComparison.Ordinal));
        using var trace = traceArgument is null ? null : new ExecutionTrace(traceArgument[prefix.Length..]);
        var start = new ProcessStartInfo(executable) { WorkingDirectory = cwd, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var argument in arguments) start.ArgumentList.Add(argument == traceArgument ? "--execution_log_binary_file=" + trace!.Pipe : argument);
        if (trace is not null) start.ArgumentList.Add("--execution_log_sort=false");
        using var process = Process.Start(start)!; var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
        if (!process.WaitForExit(3600000)) { process.Kill(true); process.WaitForExit(); throw new IOException("Build timed out after one hour"); }
        Task.WaitAll(stdout, stderr); File.WriteAllText(log, stdout.Result + stderr.Result);
        trace?.Complete();
        return process.ExitCode;
    }
    internal static List<JsonNode> Events(byte[] bytes)
    {
        var reader = new Utf8JsonReader(bytes, new JsonReaderOptions { AllowMultipleValues = true }); var values = new List<JsonNode>();
        while (reader.Read()) values.Add(JsonNode.Parse(ref reader)!); return values;
    }
}
