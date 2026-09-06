using System.Text.Json.Nodes;
using System.Xml.Linq;

namespace ActionRunner;

internal static class InputValidation
{
    public static void NativeRuntime(ActionRequest request)
    {
        if (request.NativeManifest is null) return;
        var manifest = JsonFiles.Read<NativeManifest>(request.NativeManifest);
        if (manifest.SchemaVersion != 1 || !request.NativeFiles.Select(f => f.Destination)
                .Order(StringComparer.Ordinal).SequenceEqual(manifest.Files.Order(StringComparer.Ordinal)))
            throw new InvalidDataException("native runtime closure declaration mismatch");
        foreach (var file in request.NativeFiles)
            if (!File.Exists(file.Source))
                throw new FileNotFoundException("native runtime closure file missing: " + file.Destination);
    }

    public static string[] StagePackages(ActionRequest request, string workspace)
    {
        var assets = JsonNode.Parse(File.ReadAllText(Path.Combine(workspace, request.Project, "obj/project.assets.json")))!;
        var resolved = assets["libraries"]!.AsObject().Where(p => p.Value!["type"]!.GetValue<string>() == "package")
            .ToDictionary(p => p.Key.ToLowerInvariant(), p => p.Value!["path"]!.GetValue<string>());
        var manifest = request.PackageManifest is null
            ? new PackageManifest(1, []) : JsonFiles.Read<PackageManifest>(request.PackageManifest);
        if (manifest.SchemaVersion != 1)
            throw new InvalidDataException("package manifest version mismatch");
        var provided = manifest.Packages.ToDictionary(p => (p.Id + "/" + p.Version).ToLowerInvariant(), p => p.Path);
        if (provided.Count != resolved.Count || provided.Any(p => !resolved.TryGetValue(p.Key, out var path) || path != p.Value))
            throw new InvalidDataException("package manifest does not match restore assets");
        var project = XDocument.Load(Path.Combine(workspace, request.Project, request.Project + ".csproj"));
        foreach (var reference in project.Descendants("PackageReference"))
        {
            var version = (string?)reference.Attribute("Version") ?? "";
            if (!version.StartsWith('[') || !version.EndsWith(']') || version.Contains(','))
                throw new InvalidDataException("package requires an exact inline version");
            if (!resolved.ContainsKey(((string?)reference.Attribute("Include") + "/" + version[1..^1]).ToLowerInvariant()))
                throw new InvalidDataException("package reference differs from restored version");
        }
        var files = request.Packages.ToDictionary(f => f.Destination, f => f.Source);
        var staged = new List<(string Source, string Target)>();
        foreach (var package in manifest.Packages)
        foreach (var entry in package.Files)
        {
            var relative = package.Path + "/" + entry.Path;
            if (!Files.ValidRelativePath(relative))
                throw new InvalidDataException("package payload path invalid");
            if (!files.TryGetValue(relative, out var source) || !File.Exists(source))
                throw new FileNotFoundException("package payload missing: " + relative);
            Files.Verify(source, entry.Size, entry.Sha256, "package payload hash mismatch: " + relative);
            staged.Add((source, Path.Combine(workspace, ".nuget/packages", relative)));
        }
        if (staged.Count != files.Count)
            throw new InvalidDataException("package payload set mismatch");
        foreach (var (source, target) in staged) Files.Copy(source, target);
        return resolved.Keys.Order(StringComparer.Ordinal).ToArray();
    }
}
