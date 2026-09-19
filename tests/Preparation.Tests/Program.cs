using System.Diagnostics;
using System.Net;
using System.Net.Sockets;
using System.Text.Json.Nodes;
using RulesMSBuild.Preparation;

// Test-only bridge: exercise the actual C# components against Python oracles
// without adding validation bypasses to the production command.
try
{
    var request = Json.Read(args[1]);
    switch (args[0])
    {
        case "execute-trace": Console.WriteLine(NativeWorkflow.Execute(request.String("executable"), request.Array("arguments").Select(value => value!.GetValue<string>()).ToList(), request.String("cwd"), request.String("log"))); break;
        case "describe-locks": Console.WriteLine(Json.Text(LockedRestore.Describe(request.String("workspace"), request.Array("projects").Select(item => item!.GetValue<string>())))); break;
        case "locked-source-profile": Console.WriteLine(LockedRestore.SourceReadDeny(request.String("workspace"), request.Array("bodies").Select(item => item!.GetValue<string>()))); break;
        case "require-source-only":
            {
                var watch = System.Diagnostics.Stopwatch.StartNew();
                NativePlan.RequireSourceOnly(Json.Read(request.String("graph")), request.Array("sources").Select(item => item!.GetValue<string>()).ToHashSet(StringComparer.Ordinal));
                Console.WriteLine(new JsonObject { ["accepted"] = true, ["seconds"] = watch.Elapsed.TotalSeconds }.ToJsonString());
                break;
            }
        case "protected-store":
            {
                var root = request.String("root"); var mutable = request.String("mutable");
                var store = new ProtectedStore();
                var protectedFirst = store.Snapshot(root, () => FileTree.Snapshot(root, true));
                var protectedSecond = store.Snapshot(root, () => FileTree.Snapshot(root, true));
                if (!JsonNode.DeepEquals(protectedFirst, protectedSecond)) throw new InvalidDataException("Protected snapshot differs");
                protectedSecond.Clear();
                if (!JsonNode.DeepEquals(protectedFirst, store.Snapshot(root, () => FileTree.Snapshot(root, true)))) throw new InvalidDataException("Caller mutated cached manifest");
                var file = Path.Combine(mutable, "input"); Directory.CreateDirectory(mutable); File.WriteAllText(file, "before");
                var old = store.Snapshot(mutable, () => FileTree.Snapshot(mutable, true)); var time = File.GetLastWriteTimeUtc(file);
                File.WriteAllText(file, "after!"); File.SetLastWriteTimeUtc(file, time);
                var changed = store.Snapshot(mutable, () => FileTree.Snapshot(mutable, true));
                if (JsonNode.DeepEquals(old, changed)) throw new InvalidDataException("Mutable tree reused");
                var restarted = new ProtectedStore(); restarted.Snapshot(root, () => FileTree.Snapshot(root, true));
                Console.WriteLine(new JsonObject { ["eligible"] = ProtectedStore.Eligible(root), ["hits"] = store.Hits, ["roots"] = store.Roots, ["fullScans"] = store.FullScans, ["restartHits"] = restarted.Hits }.ToJsonString());
                break;
            }
        case "linux-sandbox-control":
            {
                var sdk = request.String("sdk"); var folder = request.String("folder"); var sandboxOutput = request.String("output");
                Directory.CreateDirectory(folder); Directory.CreateDirectory(sandboxOutput);
                File.WriteAllText(Path.Combine(folder, "readonly"), "original");
                using var server = new TcpListener(IPAddress.Loopback, 0); server.Start();
                request["port"] = ((IPEndPoint)server.LocalEndpoint).Port;
                var childRequest = Path.Combine(sandboxOutput, "child.json"); Json.Write(childRequest, request);
                var runner = typeof(LinuxPlatform).Assembly.Location;
                var testRunner = System.Reflection.Assembly.GetExecutingAssembly().Location;
                var start = LinuxPlatform.Discovery([sdk, folder, Path.GetDirectoryName(runner)!, Path.GetDirectoryName(testRunner)!], sandboxOutput, folder);
                foreach (var arg in new[] { Path.Combine(sdk, "dotnet"), testRunner, "linux-sandbox-child", childRequest }) start.ArgumentList.Add(arg);
                start.Environment.Clear(); start.Environment["DOTNET_ROOT"] = sdk;
                using var process = Process.Start(start)!;
                var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
                if (!process.WaitForExit(15000)) { process.Kill(true); throw new IOException("Sandbox control timed out"); }
                Task.WaitAll(stdout, stderr);
                if (process.ExitCode != 0) throw new IOException(stderr.Result);
                Console.WriteLine(stdout.Result);
            }
            break;
        case "linux-sandbox-child":
            {
                var hidden = !File.Exists(request.String("hidden"));
                var read = File.ReadAllText(Path.Combine(request.String("folder"), "readonly")) == "original";
                var deniedWrite = false;
                try { File.WriteAllText(Path.Combine(request.String("folder"), "readonly"), "changed"); }
                catch (UnauthorizedAccessException) { deniedWrite = true; }
                catch (IOException) { deniedWrite = true; }
                var deniedNetwork = false;
                using var socket = new TcpClient();
                try { await socket.ConnectAsync(IPAddress.Loopback, request["port"]!.GetValue<int>()).WaitAsync(TimeSpan.FromSeconds(2)); }
                catch (Exception error) when (error is SocketException or TimeoutException) { deniedNetwork = true; }
                Console.WriteLine(Json.Text(new JsonObject { ["hidden"] = hidden, ["read"] = read, ["deniedWrite"] = deniedWrite, ["deniedNetwork"] = deniedNetwork }));
            }
            break;
        case "action-cache-endpoint":
            Console.WriteLine(Json.Text(JsonValue.Create(ActionCache.Endpoint(request.String("endpoint")))));
            break;
        case "action-cache-gate":
            using (var gate = new ActionCache(request.String("endpoint"), request.String("directory"), request["upload"]?.GetValue<bool>() == true))
            using (var gateClient = new HttpClient())
            {
                var responses = new JsonArray();
                foreach (var item in request.Array("requests"))
                {
                    using var message = new HttpRequestMessage(new HttpMethod(item!.String("method")), gate.Url + item.String("path"));
                    if (item!["body"] is { } body) message.Content = new ByteArrayContent(Convert.FromBase64String(body.GetValue<string>()));
                    using var response = await gateClient.SendAsync(message);
                    responses.Add(new JsonObject { ["status"] = (int)response.StatusCode, ["body"] = Convert.ToBase64String(await response.Content.ReadAsByteArrayAsync()) });
                }
                var beforePublish = gate.Statistics;
                var upstreamBefore = new JsonArray();
                foreach (var name in request.Array("probeBeforePublish"))
                {
                    using var response = await gateClient.GetAsync(request.String("endpoint") + "/" + name!.GetValue<string>());
                    upstreamBefore.Add((int)response.StatusCode);
                }
                if (request["publish"]?.GetValue<bool>() == true) gate.Publish();
                gate.Stop();
                Console.WriteLine(Json.Text(new JsonObject { ["responses"] = responses, ["beforePublish"] = beforePublish, ["upstreamBefore"] = upstreamBefore, ["afterPublish"] = gate.Statistics }));
            }
            break;
        case "alias-snapshot":
            var aliasRoot = request.String("path"); var aliasProfile = new IntegrityProfile();
            var aliasBaseline = FileTree.Snapshot(aliasRoot, true, deduplicateLinks: false);
            var aliasActual = FileTree.Snapshot(aliasRoot, true, aliasProfile);
            if (!JsonNode.DeepEquals(aliasActual, aliasBaseline)) throw new InvalidDataException("Alias manifests differ");
            if (request["mutate"]?.GetValue<bool>() == true)
            {
                var file = Path.Combine(aliasRoot, "value"); var modified = File.GetLastWriteTimeUtc(file);
                File.WriteAllText(file, "other"); File.SetLastWriteTimeUtc(file, modified);
                FileTree.Verify(aliasRoot, aliasActual, true);
            }
            Console.WriteLine(Json.Text(aliasProfile.Report()));
            break;
        case "integrity-profile":
            var roots = request.Array("roots").Select(n => n!.GetValue<string>()).ToArray();
            var baseline = roots.ToDictionary(p => p, p => FileTree.Snapshot(p, true, deduplicateLinks: false));
            var samples = new JsonArray();
            for (var iteration = 0; iteration < 5; iteration++)
            {
                var profile = new IntegrityProfile();
                var started = IntegrityProfile.Begin();
                var beforeGc = Enumerable.Range(0, 3).Select(GC.CollectionCount).ToArray();
                var actual = roots.ToDictionary(p => p, p => FileTree.Snapshot(p, true, profile, request["deduplicateLinks"]?.GetValue<bool>() != false));
                profile.End("snapshotTotal", started);
                started = IntegrityProfile.Begin();
                foreach (var root in roots) if (!JsonNode.DeepEquals(actual[root], baseline[root])) throw new InvalidDataException("Profile snapshot differs");
                profile.End("comparison", started);
                started = IntegrityProfile.Begin();
                foreach (var root in roots) _ = Json.Digest(actual[root]);
                profile.End("canonicalDigest", started);
                var measured = profile.Report(); measured["iteration"] = iteration;
                measured["collections"] = new JsonArray(Enumerable.Range(0, 3).Select(g => (JsonNode?)JsonValue.Create(GC.CollectionCount(g) - beforeGc[g])).ToArray());
                samples.Add(measured);
            }
            var identities = new JsonObject(); foreach (var root in roots) identities[Path.GetFileName(root)] = Json.Digest(baseline[root]);
            Console.WriteLine(Json.Text(new JsonObject { ["samples"] = samples, ["rootDigests"] = identities }));
            break;
        case "remote-meter":
            using (var remote = new RemoteCache(request.String("endpoint")))
            {
                remote.Fetch(request.String("digest"));
                var data = System.Text.Encoding.UTF8.GetBytes(request.String("data"));
                remote.Upload(data); remote.Upload(data);
                Console.WriteLine(Json.Text(remote.Statistics));
            }
            break;
        case "worker-compatible":
            WorkerIdentity.RequireCompatible(request["producer"], request["consumer"]!);
            Console.WriteLine(Json.Text(JsonValue.Create(true)));
            break;
        case "worker-snapshot":
            using (var remote = new RemoteCache(request.String("endpoint")))
                Console.WriteLine(Json.Text(remote.Snapshot(request.String("digest"), request["worker"])));
            break;
        case "verification":
            var verification = new FileTree.Verification();
            var leased = request.String("path"); var expected = FileTree.Snapshot(leased);
            if (request["mutate"]?.GetValue<bool>() == true)
            {
                var valuePath = Path.Combine(leased, "value"); var timestamp = File.GetLastWriteTimeUtc(valuePath);
                File.WriteAllText(valuePath, "other"); File.SetLastWriteTimeUtc(valuePath, timestamp);
            }
            verification.Verify(leased, expected);
            var second = expected.DeepClone();
            if (request["differentExpectation"]?.GetValue<bool>() == true) second["value"]!["sha256"] = new string('0', 64);
            verification.Verify(leased, second);
            if (request["laterMutation"]?.GetValue<bool>() == true)
            {
                File.WriteAllText(Path.Combine(leased, "value"), "changed");
                new FileTree.Verification().Verify(leased, expected);
            }
            if (request["linkedPolicy"]?.GetValue<bool>() == true) verification.Verify(leased, expected, true);
            Console.WriteLine(Json.Text(new JsonObject { ["requests"] = verification.Requests, ["scans"] = verification.Scans }));
            break;
        case "hash-regular":
            var content = FileTree.HashRegular(request.String("path"));
            Console.WriteLine(Json.Text(new JsonObject { ["size"] = content.Length, ["sha256"] = content.Digest }));
            break;
        case "snapshot":
            Console.WriteLine(Json.Text(FileTree.Snapshot(request.String("path"))));
            break;
        case "copy":
            FileTree.Copy(request.String("source"), request.String("output"), request["preserveModes"]?.GetValue<bool>() ?? true);
            Console.WriteLine(Json.Text(FileTree.Snapshot(request.String("output"))));
            break;
        case "remove":
            FileTree.Remove(request.String("path"));
            break;
        case "nuget":
            Console.WriteLine(Json.Text(NuGetInputs.Stage(request.String("source"), request.String("output"), request.String("cache"))));
            break;
        case "orchard-profile":
            var orchardProfile = new OrchardProfile(request.String("repository"), request.String("workspace"), request.String("sdk"));
            Console.WriteLine(Json.Text(new JsonObject { ["accepted"] = orchardProfile.Accept(request.String("path"), request.String("sha256")), ["packages"] = Json.Strings(orchardProfile.Packages) }));
            break;
        case "discovery":
            var discovery = new Discovery(request.String("repository"), request.String("sdk"), request.String("workspace"), request.String("output"), new string('a', 64), new Dictionary<string, JsonObject>());
            var discovered = discovery.Capture(request.String("entry"));
            Console.WriteLine(Json.Text(new JsonObject { ["projects"] = discovered.Array("nodes").Count }));
            break;
        case "bind-sources":
            NativePlan.BindSources(request);
            break;
        case "native-plan":
            NativePlan.Materialize(request.String("prepared"), request["graph"]!, request.String("output"), request.String("toolchain"), includePayload: request["includePayload"]?.GetValue<bool>() ?? true, repository: request["repository"]?.GetValue<string>());
            break;
        case "refresh":
            Console.WriteLine(Json.Text(NativePlan.Refresh(request.String("plan"), request.String("workspace"), request["before"]!, request["after"]!)));
            break;
        case "bundle":
            Console.WriteLine(Json.Text(RemoteCache.ValidateBundle(RemoteCache.Unpack(File.ReadAllBytes(request.String("archive"))))));
            break;
        case "publish":
            using (var remote = new RemoteCache(request.String("endpoint")))
                Console.WriteLine(Json.Text(JsonValue.Create(remote.Publish(request.String("cache"), null, null))));
            break;
        case "workflow":
            Console.WriteLine(Json.Text(NativeWorkflow.Run(request)));
            break;
        case "remote-preparation":
            using (var remote = new RemoteCache(request.String("endpoint")))
                Console.WriteLine(Json.Text(remote.Preparation(request.String("digest"), request.String("output"), [])));
            break;
        case "frameworks":
            Console.WriteLine(Json.Text(GraphPreparation.FrameworkSelections(request.AsObject().ToDictionary(p => p.Key, p => p.Value!), request.AsObject().Select(p => p.Key).ToHashSet())));
            break;
        case "closures":
            var closures = GraphPreparation.Closures(request.AsObject().ToDictionary(p => p.Key, p => p.Value!));
            var result = new JsonObject();
            foreach (var (key, value) in closures) result[key] = Json.Strings(value.Order(StringComparer.Ordinal));
            Console.WriteLine(Json.Text(result));
            break;
        case "compile":
            CompileBoundary.Validate(request.String("workspace"), request["graph"]!, new Packages(request.String("workspace"), request.String("output"), request.String("repository")));
            break;
        case "package":
            var output = request.String("output");
            Directory.CreateDirectory(output);
            var packages = new Packages(request.String("workspace"), output, request.String("repository"), writePayload: request["writePayload"]?.GetValue<bool>() ?? true);
            var staged = packages.Stage("App/App.csproj", "App/obj/project.assets.json", "net10.0", "app");
            if (request["mutate"] is { } mutate) File.WriteAllText(mutate.GetValue<string>(), "corrupt");
            packages.Verify();
            Console.WriteLine(Json.Text(new JsonObject { ["manifest"] = staged.Manifest, ["paths"] = Json.Strings(staged.Paths) }));
            break;
        default: throw new ArgumentException("Unknown test component");
    }
}
catch (Exception error)
{
    Console.Error.WriteLine(error.Message);
    return 1;
}
return 0;
