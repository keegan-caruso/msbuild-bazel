using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;
using System.Xml.Linq;

internal sealed record PackageInput(string Id, string Version, string Directory);
internal sealed record PackageRequest(string Id, string Version, string Archive, string ContentHash, string ArchiveSha256, string Output);
internal static class Package
{
    public static void Extract(PackageRequest request)
    {
        var id = Program.Safe(request.Id.ToLowerInvariant()); var version = Program.Safe(request.Version);
        if (id.Contains('/') || version.Contains('/')) throw new InvalidDataException("Invalid package identity");
        var bytes = File.ReadAllBytes(request.Archive);
        if (Convert.FromBase64String(request.ContentHash).Length != 64) throw new InvalidDataException("Invalid NuGet content hash");
        if (!Convert.ToHexStringLower(SHA256.HashData(bytes)).Equals(request.ArchiveSha256, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Package archive differs from locked archive hash");
        Directory.CreateDirectory(request.Output);
        using var zip = new ZipArchive(new MemoryStream(bytes));
        var nuspec = zip.Entries.Single(e => !e.FullName.Contains('/') && e.FullName.EndsWith(".nuspec", StringComparison.OrdinalIgnoreCase));
        using (var stream = nuspec.Open())
        {
            var metadata = XDocument.Load(stream).Root!.Elements().Single(e => e.Name.LocalName == "metadata");
            string Value(string name) => metadata.Elements().Single(e => e.Name.LocalName == name).Value;
            if (!Value("id").Equals(id, StringComparison.OrdinalIgnoreCase) || Value("version") != version) throw new InvalidDataException("Package identity differs from lock");
        }
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { ".nupkg.metadata", id + "." + version + ".nupkg", id + "." + version + ".nupkg.sha512" };
        foreach (var entry in zip.Entries)
        {
            if (entry.FullName.EndsWith('/')) continue;
            var relative = Program.Safe(entry.FullName.Replace("%2B", "+", StringComparison.OrdinalIgnoreCase));
            if (!names.Add(relative)) throw new InvalidDataException("Duplicate package entry");
            var path = Path.Combine(request.Output, relative); Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            using var input = entry.Open(); using var output = File.Create(path); input.CopyTo(output);
        }
        var archive = Path.Combine(request.Output, id + "." + version + ".nupkg");
        File.WriteAllBytes(archive, bytes); File.WriteAllText(archive + ".sha512", request.ContentHash);
        File.WriteAllText(Path.Combine(request.Output, ".nupkg.metadata"), JsonSerializer.Serialize(new { version = 2, contentHash = request.ContentHash, source = "bazel-locked-package" }));
    }
}
