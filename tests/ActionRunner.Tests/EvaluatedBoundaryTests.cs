using ActionRunner;

internal static class EvaluatedBoundaryTests
{
    public static void Run()
    {
        var root = Directory.CreateTempSubdirectory("evaluated-boundary-").FullName;
        try
        {
            // A pinned content file must not become a current dependency DLL,
            // even if its bytes happened to match the producer at cache creation.
            var runtimeNames = new HashSet<string>(["Lib.dll", "Lib.pdb", "Lib.xml"], StringComparer.OrdinalIgnoreCase);
            if (!EvaluatedBoundary.CopiesProjectRuntime("Always", ["pinned.bin", "nested\\LIB.dll"], runtimeNames) ||
                !EvaluatedBoundary.CopiesProjectRuntime("PreserveNewest", ["Lib.pdb"], runtimeNames) ||
                EvaluatedBoundary.CopiesProjectRuntime("Never", ["Lib.dll"], runtimeNames) ||
                EvaluatedBoundary.CopiesProjectRuntime("Always", ["settings.json"], runtimeNames))
                throw new InvalidOperationException("declared runtime overlay classification failed");
            const string project = "Lib/Lib.csproj";
            var lib = Path.Combine(root, "lib");
            var app = Path.Combine(root, "app");
            void Write(string bundle, string path, string value)
            {
                var target = Path.Combine(bundle, "artifacts", path);
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                File.WriteAllText(target, value);
            }
            string Identity() => EvaluatedBoundary.Identity(lib, project, [project], []);
            Write(lib, "Lib/obj/Release/net10.0/ref/Lib.dll", "API");
            Write(lib, "Lib/bin/Release/net10.0/Lib.dll", "old implementation");
            Write(lib, "Lib/bin/Release/net10.0/Lib.deps.json", "{\"libraries\":{},\"targets\":{}}");
            Write(lib, "Lib/bin/Release/net10.0/Package.dll", "package runtime");
            File.WriteAllText(Path.Combine(lib, "results.json"), "{\"targets\":{\"Build\":[]}}");
            CompileBoundary.Seal(lib);
            var original = Identity();
            Write(lib, "Lib/bin/Release/net10.0/Lib.dll", "current body with different length");
            CompileBoundary.Seal(lib);
            if (Identity() != original) throw new InvalidOperationException("body invalidated compilation contract");
            foreach (var path in new[] { "Lib/obj/Release/net10.0/ref/Lib.dll", "Lib/bin/Release/net10.0/Lib.deps.json", "Lib/bin/Release/net10.0/Package.dll" })
            {
                var file = Path.Combine(lib, "artifacts", path);
                var saved = File.ReadAllText(file);
                Write(lib, path, saved + " ");
                CompileBoundary.Seal(lib);
                if (Identity() == original) throw new InvalidOperationException("compile/runtime contract change ignored: " + path);
                Write(lib, path, saved);
                CompileBoundary.Seal(lib);
            }
            if (EvaluatedBoundary.Identity(lib, project, [project], ["transitive API changed"]) == original)
                throw new InvalidOperationException("transitive contract ignored");
            Write(lib, "Lib/bin/Release/net10.0/Lib.deps.json", "{\"libraries\":{\"Package/1\":{\"type\":\"package\"}},\"targets\":{\"net10\":{\"Package/1\":{\"runtime\":{\"lib/net10/Lib.dll\":{}}}}}}");
            CompileBoundary.Seal(lib);
            try
            {
                Identity();
                throw new InvalidOperationException("package runtime classified as project implementation");
            }
            catch (InvalidDataException) { }
            Write(lib, "Lib/bin/Release/net10.0/Lib.deps.json", "{\"libraries\":{},\"targets\":{}}");
            File.WriteAllText(Path.Combine(lib, "results.json"), "{\"targets\":{\"Build\":[{\"spec\":\"x\",\"metadata\":{\"B\":\"2\",\"A\":\"1\"}}],\"Other\":[]}}");
            CompileBoundary.Seal(lib);
            var ordered = Identity();
            File.WriteAllText(Path.Combine(lib, "results.json"), "{\"targets\":{\"Other\":[],\"Build\":[{\"metadata\":{\"A\":\"1\",\"B\":\"2\"},\"spec\":\"x\"}]}}");
            CompileBoundary.Seal(lib);
            if (Identity() != ordered) throw new InvalidOperationException("JSON property order invalidated compilation");
            Write(lib, "Lib/bin/Release/net10.0/Lib.pdb", "new symbols");
            CompileBoundary.Seal(lib);
            if (Identity() == ordered) throw new InvalidOperationException("runtime membership change ignored");
            Write(app, "App/bin/Release/net10.0/App.dll", "consumer implementation");
            Write(app, "App/bin/Release/net10.0/Lib.dll", "old implementation");
            Write(app, "App/bin/Release/net10.0/Package.dll", "consumer package selection");
            File.WriteAllText(Path.Combine(app, "results.json"), "{\"targets\":{}}");
            CompileBoundary.Seal(app);
            var seal = Files.Hash(Path.Combine(app, "bundle.json"));
            var workspace = Path.Combine(root, "workspace");
            try
            {
                EvaluatedBoundary.Compose(app, "App/App.csproj", new() { [project] = lib }, workspace, verifySelection: true);
                throw new InvalidOperationException("fresh SDK output override accepted as a producer-owned file");
            }
            catch (InvalidDataException) { }
            if (Directory.Exists(workspace)) throw new InvalidOperationException("ambiguous fresh output wrote runtime files");
            EvaluatedBoundary.Compose(app, "App/App.csproj", new() { [project] = lib }, workspace);
            if (File.ReadAllText(Path.Combine(workspace, "App/bin/Release/net10.0/Lib.dll")) != "current body with different length")
                throw new InvalidOperationException("runtime did not use current implementation");
            if (File.Exists(Path.Combine(workspace, "App/bin/Release/net10.0/Package.dll")) || Files.Hash(Path.Combine(app, "bundle.json")) != seal)
                throw new InvalidOperationException("composition changed package selection or immutable bundle");
            var refreshed = Path.Combine(root, "refreshed");
            if (!EvaluatedBoundary.RefreshBundle(app, "App/App.csproj", new() { [project] = lib }, refreshed))
                throw new InvalidOperationException("historical seed runtime was not refreshed");
            CompileBoundary.Validate(refreshed);
            if (File.ReadAllText(Path.Combine(refreshed, "artifacts/App/bin/Release/net10.0/Lib.dll")) != "current body with different length" ||
                File.ReadAllText(Path.Combine(refreshed, "artifacts/App/bin/Release/net10.0/Package.dll")) != "consumer package selection" || Files.Hash(Path.Combine(app, "bundle.json")) != seal)
                throw new InvalidOperationException("seed refresh changed immutable input or package selection");
            if (EvaluatedBoundary.RefreshBundle(refreshed, "App/App.csproj", new() { [project] = lib }, Path.Combine(root, "unchanged")) || Directory.Exists(Path.Combine(root, "unchanged")))
                throw new InvalidOperationException("current seeds were copied unnecessarily");
            Write(lib, "Lib/bin/Release/net10.0/Lib.dll", "corrupt");
            try
            {
                EvaluatedBoundary.Compose(app, "App/App.csproj", new() { [project] = lib }, Path.Combine(root, "rejected"));
                throw new InvalidOperationException("corrupt current producer accepted");
            }
            catch (InvalidDataException) { }
            try
            {
                EvaluatedBoundary.RefreshBundle(app, "App/App.csproj", new() { [project] = lib }, Path.Combine(root, "corrupt-seed"));
                throw new InvalidOperationException("corrupt producer refreshed a seed");
            }
            catch (InvalidDataException) { }
            if (Directory.Exists(Path.Combine(root, "corrupt-seed"))) throw new InvalidOperationException("corrupt seed refresh wrote partial output");
            if (Directory.Exists(Path.Combine(root, "rejected"))) throw new InvalidOperationException("corruption wrote partial runtime");
        }
        finally { Directory.Delete(root, true); }
    }
}
