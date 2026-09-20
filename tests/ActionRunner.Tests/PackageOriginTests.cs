using System.Text.Json.Nodes;
using ActionRunner;

internal static class PackageOriginTests
{
    internal static void Run()
    {
        var root = Directory.CreateTempSubdirectory("package-origin-tests-").FullName;
        try
        {
            var bundle = Path.Combine(root, "bundle");
            Directory.CreateDirectory(Path.Combine(bundle, "artifacts"));
            var original = Path.Combine(bundle, "artifacts", "Package.dll");
            File.WriteAllText(original, "package bytes");
            File.WriteAllText(Path.Combine(bundle, "artifacts", "Own.dll"), "own bytes");
            File.WriteAllText(Path.Combine(bundle, "results.json"), new JsonObject { ["project"] = "App/App.csproj", ["key"] = new string('1', 64), ["inputs"] = new string('2', 64), ["toolchain"] = new string('3', 64) }.ToJsonString());
            CompileBoundary.Seal(bundle);
            var denseSeal = File.ReadAllBytes(Path.Combine(bundle, "bundle.json"));
            var source = Path.Combine(root, "declared-package.dll"); Files.Copy(original, source);
            var hash = Files.Hash(source);
            var compact = PackageOriginBundles.Compact(bundle, new Dictionary<string, string> { ["package/1.0/lib/Package.dll"] = hash });
            if (compact.Files != 1 || compact.Bytes != new FileInfo(source).Length || File.Exists(original)) throw new InvalidOperationException("Package bytes not replaced by provenance");
            var inputs = new Dictionary<string, string> { ["package/1.0/lib/Package.dll"] = source };
            var view = new PackageOriginBundles(inputs);
            var expanded = view.Expand(bundle, Path.Combine(root, "expanded"));
            CompileBoundary.Validate(expanded);
            if (!denseSeal.SequenceEqual(File.ReadAllBytes(Path.Combine(expanded, "bundle.json")))) throw new InvalidOperationException("Expansion changed logical seal");
            view.VerifyUnchanged();
            void Reject(Action action)
            {
                try { action(); throw new InvalidOperationException("Invalid provenance accepted"); }
                catch (InvalidDataException) { }
            }
            var savedOrigins = File.ReadAllText(Path.Combine(bundle, "package-origins.json"));
            var savedSeal = File.ReadAllText(Path.Combine(bundle, "bundle.json"));
            inputs["package/1.0/lib/Other.dll"] = source;
            File.WriteAllText(Path.Combine(bundle, "package-origins.json"), "{\"Package.dll\":\"package/1.0/lib/Other.dll\"}");
            var changedSeal = JsonNode.Parse(savedSeal)!;
            changedSeal["packageOriginsSha256"] = Files.Hash(Path.Combine(bundle, "package-origins.json"));
            File.WriteAllText(Path.Combine(bundle, "bundle.json"), changedSeal.ToJsonString());
            new PackageOriginBundles(inputs).Read(bundle); // Valid new mapping, wrong lifetime.
            Reject(view.VerifyUnchanged);
            File.WriteAllText(Path.Combine(bundle, "package-origins.json"), savedOrigins);
            File.WriteAllText(Path.Combine(bundle, "bundle.json"), savedSeal);
            Reject(() => new PackageOriginBundles(new Dictionary<string, string>()).Read(bundle));
            File.WriteAllText(source, "PACKAGE BYTES");
            Reject(view.VerifyUnchanged);
            File.WriteAllText(source, "package bytes");
            File.WriteAllText(original, "unexpected physical copy");
            Reject(() => new PackageOriginBundles(inputs).Read(bundle));
            File.Delete(original);
            var originsPath = Path.Combine(bundle, "package-origins.json");
            File.WriteAllText(originsPath, "{\"Package.dll\":\"../escape\"}");
            var sealPath = Path.Combine(bundle, "bundle.json");
            var seal = JsonNode.Parse(File.ReadAllText(sealPath))!; seal["packageOriginsSha256"] = Files.Hash(originsPath); File.WriteAllText(sealPath, seal.ToJsonString());
            Reject(() => new PackageOriginBundles(inputs).Read(bundle));
        }
        finally { Directory.Delete(root, true); }
    }
}
