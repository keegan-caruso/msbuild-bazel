using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;
using System.Xml.Linq;

namespace ActionRunner;

internal static class PackageInputs
{
    public static string[] Stage(ActionRequest request, string workspace)
    {
        var projectName = request.Project.ToString();
        var projectPath = request.GraphProject ?? Path.Combine(projectName, projectName + ".csproj");
        var assetsPath = Path.Combine(workspace, request.GraphAssetsFile ?? Path.Combine(Path.GetDirectoryName(projectPath)!, "obj/project.assets.json"));
        var assets = JsonFiles.Read<RestoreAssets>(assetsPath);
        using var assetsDocument = JsonDocument.Parse(File.ReadAllText(assetsPath));
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
        var project = XDocument.Load(Path.Combine(workspace, projectPath));
        foreach (var reference in project.Descendants().Where(element => element.Name.LocalName == "PackageReference"))
        {
            // The exporter evaluates conditional references before sealing the graph.
            // Raw XML cannot decide whether another framework's reference is active.
            if (request.GraphProject is not null && reference.AncestorsAndSelf().Any(element => element.Attribute("Condition") is not null)) continue;
            var version = (string?)reference.Attribute("Version") ?? "";
            // GraphExport validates evaluated central/imported versions against restore;
            // raw project XML cannot resolve Directory.Packages.props or properties.
            if (request.GraphProject is not null && version.Length == 0) continue;
            var selected = PilotPackagePolicy.SelectedVersion((string?)reference.Attribute("Include") ?? "", version);
            if (selected is null)
                throw new InvalidDataException("package requires an exact inline version");
            if (!resolved.ContainsKey((string?)reference.Attribute("Include") + "/" + selected))
                throw new InvalidDataException("package reference differs from restored version");
        }
        var files = request.Packages.ToDictionary(f => f.Destination, f => f.Source);
        foreach (var package in manifest.Packages)
        {
            var pin = PilotPackagePolicy.Find(package.Id + "/" + package.Version);
            if (request.GraphProject is not null) VerifyAssetRoles(assetsDocument.RootElement, package.Id + "/" + package.Version, pin);
            if (pin is not null) VerifyPilot(package, pin, files, assets);
            if (request.GraphProject is not null)
                foreach (var entry in package.Files)
                {
                    var segments = entry.Path.Split('/');
                    var root = segments[0].ToLowerInvariant();
                    var analyzerPayload = segments.Length == 4 &&
                        entry.Path.StartsWith("analyzers/dotnet/cs/", StringComparison.Ordinal) &&
                        entry.Path.EndsWith(".dll", StringComparison.Ordinal);
                    if (!analyzerPayload && new[] { "runtimes", "native", "analyzers", "build", "buildtransitive", "buildmultitargeting", "content", "contentfiles", "tools" }.Contains(root) &&
                        !(pin?.AdditionalRoots.Contains(root) ?? false))
                        throw new InvalidDataException("unsupported graph package payload category");
                }
        }
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
    internal static void VerifyAssetRoles(JsonElement assets, string identity, PilotPackagePin? pin)
    {
        if (!assets.TryGetProperty("targets", out var targets)) return;
        foreach (var framework in targets.EnumerateObject())
            foreach (var package in framework.Value.EnumerateObject())
            {
                if (!package.Name.Equals(identity, StringComparison.OrdinalIgnoreCase)) continue;
                foreach (var role in package.Value.EnumerateObject())
                {
                    var name = role.Name.ToLowerInvariant();
                    if (!new[] { "native", "runtimetargets", "resource", "build", "buildmultitargeting", "buildtransitive", "contentfiles" }.Contains(name)) continue;
                    if (role.Value.ValueKind == JsonValueKind.Object && !role.Value.EnumerateObject().Any()) continue;
                    if (!(pin?.AssetRoles.Contains(name) ?? false))
                        throw new InvalidDataException("unsupported graph package asset role: " + identity + ":" + role.Name);
                }
            }
    }
    private static void VerifyPilot(Package package, PilotPackagePin pin, Dictionary<string, string> files, RestoreAssets assets)
    {
        var identity = package.Id + "/" + package.Version;
        if (!assets.Libraries.TryGetValue(identity, out var library) || library.Sha512 != pin.RestoreContentHash)
            throw new InvalidDataException("qualified package restore content hash mismatch");
        var archiveName = package.Id.ToLowerInvariant() + "." + package.Version + ".nupkg";
        if (!files.TryGetValue(package.Path + "/" + archiveName, out var archive) || !File.Exists(archive) || Files.Hash(archive) != pin.ArchiveSha256)
            throw new InvalidDataException("qualified package archive hash mismatch");
        var expected = new Dictionary<string, (long Size, string Hash)>(StringComparer.Ordinal);
        using (var zip = ZipFile.OpenRead(archive))
            foreach (var entry in zip.Entries)
            {
                if (entry.FullName.EndsWith('/')) continue;
                var name = entry.FullName.EndsWith(".nuspec", StringComparison.OrdinalIgnoreCase) ? entry.FullName.ToLowerInvariant() : entry.FullName;
                using var stream = entry.Open();
                expected.Add(name, (entry.Length, Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant()));
            }
        using var archiveStream = File.OpenRead(archive);
        expected.Add(archiveName, (archiveStream.Length, pin.ArchiveSha256));
        var marker = System.Text.Encoding.ASCII.GetBytes(Convert.ToBase64String(SHA512.HashData(File.ReadAllBytes(archive))));
        expected.Add(archiveName + ".sha512", (marker.Length, Convert.ToHexString(SHA256.HashData(marker)).ToLowerInvariant()));
        if (package.Files.Length != expected.Count || package.Files.Select(file => file.Path).Distinct().Count() != expected.Count ||
            package.Files.Any(file => !expected.TryGetValue(file.Path, out var value) || value.Size != file.Size || value.Hash != file.Sha256))
            throw new InvalidDataException("qualified package manifest differs from pinned archive");
    }

}
