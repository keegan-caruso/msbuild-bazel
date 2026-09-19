using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace RulesMSBuild.Preparation;

// Archive acquisition remains a repository operation; this deterministic transform
// can be a separately cached Bazel action without changing NuGet resolution.
internal static class PackageExtraction
{
    public static void Run(JsonNode request)
    {
        var package = Host.Safe(request.String("package")); var parts = package.Split('/');
        if (parts.Length != 2 || package != package.ToLowerInvariant()) throw new InvalidDataException("Invalid NuGet package path");
        var contentHash = request.String("contentHash");
        if (Convert.FromBase64String(contentHash).Length != 64) throw new InvalidDataException("Invalid NuGet content hash");
        var raw = File.ReadAllBytes(request.String("archive"));
        var archiveHash = Convert.ToBase64String(SHA512.HashData(raw));
        var pin = request["pin"];
        if (pin is null ? archiveHash != contentHash : pin.String("restoreContentHash") != contentHash || pin.String("archiveSha256") != Json.Sha(raw))
            throw new InvalidDataException("NuGet archive hash mismatch");
        var output = request.String("output");
        if (Directory.Exists(output) && Directory.EnumerateFileSystemEntries(output).Any()) throw new InvalidDataException("Package output must be empty");
        Directory.CreateDirectory(output);
        var archiveName = parts[0] + "." + parts[1] + ".nupkg";
        var comparer = OperatingSystem.IsMacOS() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;
        var directories = new Dictionary<string, string>(comparer);
        var names = new HashSet<string>(comparer)
        {
            archiveName, archiveName + ".sha512", ".nupkg.metadata"
        };
        using var zip = new ZipArchive(new MemoryStream(raw));
        // Validate all names before creating any archive payload files.
        var entries = new List<(ZipArchiveEntry Entry, string Name)>();
        foreach (var entry in zip.Entries)
        {
            var kind = (entry.ExternalAttributes >> 16) & 0xF000;
            if (kind is not (0 or 0x8000 or 0x4000)) throw new InvalidDataException("NuGet archive contains a non-regular entry");
            var rawName = entry.FullName;
            if (pin is not null) rawName = Regex.Replace(rawName, "/{2,}", "/");
            var directory = rawName.EndsWith('/');
            rawName = Host.Safe(directory ? rawName[..^1] : rawName);
            var name = Host.Safe(rawName.Replace("%2B", "+", StringComparison.OrdinalIgnoreCase));
            var segments = rawName.Split('/');
            for (var count = 1; count <= segments.Length - (directory ? 0 : 1); count++)
            {
                var original = string.Join('/', segments.Take(count));
                var normalized = original.Replace("%2B", "+", StringComparison.OrdinalIgnoreCase);
                if (directories.TryGetValue(normalized, out var previous) && !comparer.Equals(previous, original))
                    throw new InvalidDataException("Conflicting normalized NuGet directory: " + normalized);
                directories[normalized] = original;
            }
            if (directory) continue;
            if (!name.Contains('/') && name.EndsWith(".nuspec", StringComparison.OrdinalIgnoreCase)) name = name.ToLowerInvariant();
            if (!names.Add(name)) throw new InvalidDataException("Conflicting normalized NuGet path: " + name);
            entries.Add((entry, name));
        }
        foreach (var (entry, name) in entries)
        {
            var path = Path.Combine(output, name); Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            using var source = entry.Open(); using var target = new FileStream(path, FileMode.CreateNew, FileAccess.Write); source.CopyTo(target);
        }
        File.WriteAllBytes(Path.Combine(output, archiveName), raw);
        File.WriteAllText(Path.Combine(output, archiveName + ".sha512"), archiveHash);
        Json.Write(Path.Combine(output, ".nupkg.metadata"), new JsonObject { ["version"] = 2, ["contentHash"] = contentHash, ["source"] = "https://api.nuget.org/v3/index.json" });
    }
}
