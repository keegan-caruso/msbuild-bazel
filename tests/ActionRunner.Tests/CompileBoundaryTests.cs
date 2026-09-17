using System.Text.Json.Nodes;
using ActionRunner;

internal static class CompileBoundaryTests
{
    public static void Run()
    {
        var root = Directory.CreateTempSubdirectory("compile-boundary-").FullName;
        try
        {
            var own = Path.Combine(root, "own");
            const string assembly = "Library/bin/Release/net10.0/Library.dll";
            const string reference = "Library/obj/Release/net10.0/ref/Library.dll";
            Directory.CreateDirectory(Path.Combine(own, "artifacts", Path.GetDirectoryName(assembly)!));
            Files.Copy(Write(root, "reference", "API"), Path.Combine(own, "artifacts", reference));
            Files.Copy(Write(root, "implementation", "body-one"), Path.Combine(own, "artifacts", assembly));
            File.WriteAllText(Path.Combine(own, "results.json"), """
                {"targets":{"Build":[{"spec":"${WORKSPACE}/Library/bin/Release/net10.0/Library.dll",
                "metadata":{"ReferenceAssembly":"${WORKSPACE}/Library/obj/Release/net10.0/ref/Library.dll"}}],
                "GetCopyToOutputDirectoryItems":[],"GetCopyToPublishDirectoryItems":[],"GetNativeManifest":[]}}
                """);
            File.WriteAllText(Path.Combine(own, "artifacts/Library/bin/Release/net10.0/Library.deps.json"), """
                {"runtimeTarget":{"name":"net10"},"libraries":{"Library/1":{"type":"project"}},
                "targets":{"net10":{"Library/1":{"runtime":{"Library.dll":{}}}}}}
                """);
            CompileBoundary.Seal(own);
            var first = Path.Combine(root, "first");
            CompileBoundary.Project(own, first);
            File.WriteAllText(Path.Combine(own, "artifacts", assembly), "body-two");
            CompileBoundary.Seal(own);
            var second = Path.Combine(root, "second");
            CompileBoundary.Project(own, second);
            foreach (var file in Directory.EnumerateFiles(first, "*", SearchOption.AllDirectories))
                if (Files.Hash(file) != Files.Hash(Path.Combine(second, Path.GetRelativePath(first, file))))
                    throw new InvalidOperationException("implementation changed compile projection");
            var app = Path.Combine(root, "app");
            Directory.CreateDirectory(Path.Combine(app, "artifacts/App/bin/Release/net10.0"));
            File.WriteAllText(Path.Combine(app, "artifacts/App/bin/Release/net10.0/App.dll"), "app");
            File.WriteAllText(Path.Combine(app, "results.json"), """
                {"targets":{"Build":[{"spec":"${WORKSPACE}/App/bin/Release/net10.0/App.dll"}]}}
                """);
            File.WriteAllText(Path.Combine(app, "artifacts/App/bin/Release/net10.0/App.deps.json"), """
                {"runtimeTarget":{"name":"net10"},"libraries":{"App/1":{"type":"project"}},
                "targets":{"net10":{"App/1":{"runtime":{"App.dll":{}}}}}}
                """);
            CompileBoundary.Seal(app);
            var runtime = Path.Combine(root, "runtime");
            CompileBoundary.Assemble(new RuntimeAssemblyRequest(app, [own], runtime));
            if (File.ReadAllText(Path.Combine(runtime, "artifacts/App/bin/Release/net10.0/Library.dll")) != "body-two")
                throw new InvalidOperationException("runtime did not refresh implementation");
            var metadata = JsonNode.Parse(File.ReadAllText(Path.Combine(runtime, "artifacts/App/bin/Release/net10.0/App.deps.json")))!;
            if (metadata["targets"]!["net10"]!["Library/1"] is null)
                throw new InvalidOperationException("transitive runtime metadata missing");
            File.WriteAllText(Path.Combine(own, "artifacts", reference), "changed-API");
            CompileBoundary.Seal(own);
            var third = Path.Combine(root, "third");
            CompileBoundary.Project(own, third);
            if (Files.Hash(Path.Combine(third, "artifacts", reference)) == Files.Hash(Path.Combine(first, "artifacts", reference)))
                throw new InvalidOperationException("API change did not change compiler inputs");
            try
            {
                CompileBoundary.Project(own, first);
                throw new InvalidOperationException("existing reference output accepted");
            }
            catch (InvalidDataException) { }
            try
            {
                CompileBoundary.Assemble(new RuntimeAssemblyRequest(app, [own], runtime));
                throw new InvalidOperationException("existing runtime output accepted");
            }
            catch (InvalidDataException) { }
            var failed = Path.Combine(root, "failed-runtime");
            var depsPath = Path.Combine(own, "artifacts/Library/bin/Release/net10.0/Library.deps.json");
            File.WriteAllText(depsPath, File.ReadAllText(depsPath).Replace("net10", "incompatible", StringComparison.Ordinal));
            CompileBoundary.Seal(own);
            try
            {
                CompileBoundary.Assemble(new RuntimeAssemblyRequest(app, [own], failed));
                throw new InvalidOperationException("incompatible runtime metadata accepted");
            }
            catch (InvalidDataException) { }
            if (File.Exists(Path.Combine(failed, "bundle.json")))
                throw new InvalidOperationException("failed composition retained a valid commit marker");
            var sealPath = Path.Combine(own, "bundle.json");
            var validSeal = File.ReadAllText(sealPath);
            foreach (var malformed in new[] { "[]", "null", "{}", "{\"schemaVersion\":\"wrong-type\"}" })
            {
                File.WriteAllText(sealPath, malformed);
                try
                {
                    CompileBoundary.Validate(own);
                    throw new InvalidOperationException("malformed seal accepted");
                }
                catch (Exception error) when (error is InvalidDataException or System.Text.Json.JsonException) { }
            }
            File.WriteAllText(sealPath, validSeal);
            File.WriteAllText(Path.Combine(own, "artifacts", assembly), "corrupt");
            try
            {
                CompileBoundary.Project(own, Path.Combine(root, "bad"));
                throw new InvalidOperationException("corrupt implementation accepted");
            }
            catch (InvalidDataException) { }
        }
        finally { Directory.Delete(root, recursive: true); }
    }

    private static string Write(string root, string name, string value)
    {
        var path = Path.Combine(root, name);
        File.WriteAllText(path, value);
        return path;
    }
}
