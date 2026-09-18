using System.Text.Json.Nodes;
using RulesMSBuild.Preparation;

// Test-only bridge: exercise the actual C# components against Python oracles
// without adding validation bypasses to the production command.
try
{
    var request = Json.Read(args[1]);
    switch (args[0])
    {
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
        case "integrity-profile":
            var roots = request.Array("roots").Select(n => n!.GetValue<string>()).ToArray();
            var baseline = roots.ToDictionary(p => p, p => FileTree.Snapshot(p, true));
            var samples = new JsonArray();
            for (var iteration = 0; iteration < 5; iteration++)
            {
                var profile = new IntegrityProfile();
                var started = IntegrityProfile.Begin();
                var beforeGc = Enumerable.Range(0, 3).Select(GC.CollectionCount).ToArray();
                var actual = roots.ToDictionary(p => p, p => FileTree.Snapshot(p, true, profile));
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
        case "native-plan":
            NativePlan.Materialize(request.String("prepared"), request["graph"]!, request.String("output"), request.String("toolchain"));
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
            var packages = new Packages(request.String("workspace"), output, request.String("repository"));
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
