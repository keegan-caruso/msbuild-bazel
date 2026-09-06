using System.Xml.Linq;

namespace ActionRunner;

internal static class PackageInputs
{
    public static string[] Stage(ActionRequest request, string workspace)
    {
        var projectName = request.Project.ToString();
        var assets = JsonFiles.Read<RestoreAssets>(Path.Combine(workspace, projectName, "obj/project.assets.json"));
        var resolved = assets.Libraries.Where(entry => entry.Value.Type == "package")
            .ToDictionary(entry => entry.Key, entry => entry.Value.Path
                ?? throw new InvalidDataException("restored package path missing: " + entry.Key), StringComparer.OrdinalIgnoreCase);
        var manifest = request.PackageManifest is null
            ? new PackageManifest(1, []) : JsonFiles.Read<PackageManifest>(request.PackageManifest);
        if (manifest.SchemaVersion != 1)
            throw new InvalidDataException("package manifest version mismatch");
        var provided = manifest.Packages.ToDictionary(p => p.Id + "/" + p.Version, p => p.Path, StringComparer.OrdinalIgnoreCase);
        if (provided.Count != resolved.Count || provided.Any(p => !resolved.TryGetValue(p.Key, out var path) || path != p.Value))
            throw new InvalidDataException("package manifest does not match restore assets");
        var project = XDocument.Load(Path.Combine(workspace, projectName, projectName + ".csproj"));
        foreach (var reference in project.Descendants("PackageReference"))
        {
            var version = (string?)reference.Attribute("Version") ?? "";
            if (!version.StartsWith('[') || !version.EndsWith(']') || version.Contains(','))
                throw new InvalidDataException("package requires an exact inline version");
            if (!resolved.ContainsKey((string?)reference.Attribute("Include") + "/" + version[1..^1]))
                throw new InvalidDataException("package reference differs from restored version");
        }
        var files = request.Packages.ToDictionary(f => f.Destination, f => f.Source);
        var staged = new List<(string Source, string Target)>();
        var payloads = manifest.Packages.SelectMany(package => package.Files,
            (package, entry) => (Path: package.Path + "/" + entry.Path, File: entry));
        foreach (var (relative, entry) in payloads)
        {
            if (!Files.ValidRelativePath(relative))
                throw new InvalidDataException("package payload path invalid");
            if (!files.TryGetValue(relative, out var source) || !File.Exists(source))
                throw new FileNotFoundException("package payload missing: " + relative);
            Files.Verify(source, entry.Size, entry.Sha256, "package payload hash mismatch: " + relative);
            staged.Add((source, Path.Combine(workspace, ".nuget/packages", relative)));
        }
        if (staged.Count != files.Count)
            throw new InvalidDataException("package payload set mismatch");
        foreach (var (source, target) in staged)
            Files.Copy(source, target);
        return resolved.Keys.Select(key => key.ToLowerInvariant()).Order(StringComparer.Ordinal).ToArray();
    }
}
