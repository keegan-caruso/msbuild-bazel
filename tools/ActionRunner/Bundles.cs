using System.Text.Json.Nodes;

namespace ActionRunner;

internal static class Bundles
{
    public static string StageDependency(ActionRequest request, Workspace workspace)
    {
        if (request.Project == ProjectKind.Shared) return workspace.Output;
        if (string.IsNullOrEmpty(request.Dependency))
            throw new InvalidDataException("App requires a Shared dependency bundle");
        var bundle = Path.Combine(workspace.Scratch, "dependency");
        Files.CopyTree(request.Dependency, bundle);
        var manifest = JsonFiles.Read<Artifact[]>(Path.Combine(bundle, "artifacts.json"));
        if (manifest.Length == 0) throw new InvalidDataException("dependency artifacts empty");
        foreach (var entry in manifest)
        {
            if (!Files.ValidRelativePath(entry.Path) ||
                !(entry.Path.StartsWith("Shared/bin/", StringComparison.Ordinal) || entry.Path.StartsWith("Shared/obj/", StringComparison.Ordinal)))
                throw new InvalidDataException("dependency artifact path invalid");
            Files.Verify(Path.Combine(bundle, "artifacts", entry.Path), entry.Size, entry.Sha256, "dependency artifact missing or corrupt");
        }
        foreach (var entry in manifest)
            Files.Copy(Path.Combine(bundle, "artifacts", entry.Path), Path.Combine(workspace.Root, entry.Path));
        return bundle;
    }

    public static void Export(ProjectKind project, Workspace workspace)
    {
        var manifest = new List<Artifact>();
        // Replay needs runtime outputs and the reference assembly; other intermediates can contain producer paths.
        string[] folders = project == ProjectKind.Shared ? ["Shared/bin", "Shared/obj/Release/net10.0/ref"] : ["App/bin"];
        foreach (var folder in folders)
            foreach (var source in Directory.EnumerateFiles(Path.Combine(workspace.Root, folder), "*", SearchOption.AllDirectories)
                         .Order(StringComparer.Ordinal))
            {
                var relative = Path.GetRelativePath(workspace.Root, source);
                Files.Copy(source, Path.Combine(workspace.Output, "artifacts", relative));
                manifest.Add(new Artifact(relative, new FileInfo(source).Length, Files.Hash(source)));
            }
        JsonFiles.Write(Path.Combine(workspace.Output, "artifacts.json"), manifest);
        Directory.Delete(workspace.Scratch, recursive: true);
        foreach (var path in Directory.EnumerateFiles(workspace.Output, "graph-*.json"))
            File.Move(path, Path.Combine(workspace.Diagnostics, Path.GetFileName(path)));
        CanonicalizeResults(Path.Combine(workspace.Output, "results.json"));
        Files.NormalizeTree(workspace.Output);
    }

    private static void CanonicalizeResults(string results)
    {
        if (File.Exists(results))
        {
            var payload = JsonNode.Parse(File.ReadAllText(results))!;
            payload["requestedTargets"] = new JsonArray(payload["requestedTargets"]!.AsArray()
                .Select(n => n!.GetValue<string>()).Order(StringComparer.Ordinal)
                .Select(s => (JsonNode?)JsonValue.Create(s)).ToArray());
            // MSBuild's object iteration order is not a contract; item order is, so only object keys are canonicalized.
            JsonFiles.Write(results, Canonicalize(payload));
        }
    }

    private static JsonNode? Canonicalize(JsonNode? node) => node switch
    {
        JsonObject obj => new JsonObject(obj.OrderBy(p => p.Key, StringComparer.Ordinal)
            .Select(p => KeyValuePair.Create(p.Key, Canonicalize(p.Value)))),
        JsonArray array => new JsonArray(array.Select(Canonicalize).ToArray()),
        _ => node?.DeepClone()
    };
}
