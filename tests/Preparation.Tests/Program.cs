using System.Text.Json.Nodes;
using RulesMSBuild.Preparation;

// Test-only bridge: exercise the actual C# components against Python oracles
// without adding validation bypasses to the production command.
try
{
    var request = Json.Read(args[1]);
    switch (args[0])
    {
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
