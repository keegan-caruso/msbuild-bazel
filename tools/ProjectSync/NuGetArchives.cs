using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;
using System.Xml.Linq;

namespace RulesMSBuild.ProjectSync;

internal sealed record NuGetArchive(string id, string version, string sha256, string archiveSha512, string[] urls);

internal static class NuGetArchives
{
    internal static async Task<NuGetArchive[]> Read(string packages)
    {
        if (!Directory.Exists(packages))
        {
            return [];
        }
        using var client = new HttpClient { Timeout = TimeSpan.FromMinutes(2) };
        var sources = new Dictionary<string, string>(StringComparer.Ordinal);
        var rows = new SortedDictionary<string, NuGetArchive>(StringComparer.Ordinal);
        foreach (var archive in Directory.GetFiles(packages, "*.nupkg", SearchOption.AllDirectories))
        {
            using var zip = ZipFile.OpenRead(archive);
            var spec = zip.Entries.Single(entry => !entry.FullName.Contains('/') && entry.FullName.EndsWith(".nuspec", StringComparison.OrdinalIgnoreCase));
            using var stream = spec.Open();
            var metadata = XDocument.Load(stream).Root!.Elements().Single(element => element.Name.LocalName == "metadata");
            var id = metadata.Elements().Single(element => element.Name.LocalName == "id").Value;
            // NuGet's installed directory already uses normalized, lowercase versions.
            var version = Path.GetFileName(Path.GetDirectoryName(archive)!);
            if (!Safe(id) || !Safe(version))
            {
                throw new InvalidDataException("Unsafe NuGet identity");
            }
            using var bytes = File.OpenRead(archive);
            var sha256 = Convert.ToHexString(SHA256.HashData(bytes)).ToLowerInvariant();
            bytes.Position = 0;
            var contentHash = Convert.ToBase64String(SHA512.HashData(bytes));
            if (File.ReadAllText(archive + ".sha512").Trim() != contentHash)
            {
                throw new InvalidDataException("NuGet archive differs from its restored archive hash: " + id);
            }
            using var installed = JsonDocument.Parse(File.ReadAllText(Path.Combine(Path.GetDirectoryName(archive)!, ".nupkg.metadata")));
            var source = installed.RootElement.GetProperty("source").GetString()!;
            if (!sources.TryGetValue(source, out var address))
            {
                ValidateUrl(source);
                using var index = JsonDocument.Parse(await client.GetStringAsync(source));
                address = index.RootElement.GetProperty("resources").EnumerateArray().Where(resource =>
                    resource.GetProperty("@type").GetString() == "PackageBaseAddress/3.0.0").Select(resource => resource.GetProperty("@id").GetString()!).FirstOrDefault()
                    ?? throw new InvalidDataException("NuGet source requires a V3 PackageBaseAddress resource");
                ValidateUrl(address);
                sources.Add(source, address);
            }
            var lower = id.ToLowerInvariant();
            var url = address.TrimEnd('/') + "/" + lower + "/" + version + "/" + lower + "." + version + ".nupkg";
            rows.Add(lower + "/" + version, new(id, version, sha256, contentHash, [url]));
        }
        return rows.Values.ToArray();
    }

    private static bool Safe(string value) => value.Length != 0 && value.All(c => char.IsAsciiLetterOrDigit(c) || c is '.' or '_' or '-');

    private static void ValidateUrl(string value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https") || uri.UserInfo.Length != 0 || uri.Query.Length != 0 || uri.Fragment.Length != 0)
        {
            throw new InvalidDataException("NuGet update requires public HTTP(S) V3 sources without embedded credentials");
        }
    }
}
