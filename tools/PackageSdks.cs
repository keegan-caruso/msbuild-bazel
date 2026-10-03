using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;

namespace RulesMSBuild;

// Package SDK resolution happens before Restore can execute. Seed only the
// exact global.json SDK versions from the already-declared local archive set.
// Inline SDK versions also need the local-only resolver feed, even without global.json.
internal static class PackageSdks
{
    internal static IDisposable? Prepare(string root)
    {
        var global = Path.Combine(root, "global.json");
        using var json = File.Exists(global) ? JsonDocument.Parse(File.ReadAllText(global), new JsonDocumentOptions
        {
            CommentHandling = JsonCommentHandling.Skip,
            AllowTrailingCommas = true
        }) : null;
        var sdks = json is not null && json.RootElement.TryGetProperty("msbuild-sdks", out var declared)
            ? declared.EnumerateObject().ToArray() : [];
        var packages = Path.Combine(root, ".nuget");
        foreach (var sdk in sdks)
        {
            var id = sdk.Name.ToLowerInvariant();
            var version = sdk.Value.GetString()?.ToLowerInvariant() ?? "";
            foreach (var part in new[] { id, version })
            {
                if (part.Length == 0 || part is "." or ".." || part.Any(c => !char.IsAsciiLetterOrDigit(c) && c is not '.' and not '-' and not '_'))
                {
                    throw new InvalidDataException("Package SDK requires an exact ID/version: " + sdk.Name);
                }
            }
            var filename = id + "." + version + ".nupkg";
            var archive = Directory.EnumerateFiles(Path.Combine(root, ".package-source"), "*.nupkg")
                .SingleOrDefault(path => Path.GetFileName(path).Equals(filename, StringComparison.OrdinalIgnoreCase));
            if (archive is null)
            {
                // global.json can name SDKs unused by the selected entry point.
                // The resolver's local-only feed below rejects missing used SDKs.
                continue;
            }
            var directory = Path.Combine(packages, id, version);
            using var stream = File.OpenRead(archive);
            var hash = Convert.ToBase64String(SHA512.HashData(stream));
            var marker = Path.Combine(directory, filename + ".sha512");
            if (!File.Exists(marker))
            {
                Directory.CreateDirectory(directory);
                ZipFile.ExtractToDirectory(archive, directory);
                File.Copy(archive, Path.Combine(directory, filename));
                File.WriteAllText(marker, hash);
                File.WriteAllText(Path.Combine(directory, ".nupkg.metadata"), JsonSerializer.Serialize(new
                {
                    version = 2,
                    contentHash = hash,
                    source = Path.Combine(root, ".package-source")
                }));
            }
            else if (File.ReadAllText(marker).Trim() != hash)
            {
                throw new InvalidDataException("Package SDK cache does not match declared archive: " + filename);
            }
        }
        var configs = Directory.GetFiles(root).Where(path => Path.GetFileName(path).Equals("NuGet.Config", StringComparison.OrdinalIgnoreCase)).ToArray();
        if (configs.Length > 1 || configs.Any(path => new FileInfo(path).LinkTarget is not null))
        {
            throw new InvalidDataException("Package SDK resolution requires one owned NuGet.Config");
        }
        var config = configs.SingleOrDefault() ?? Path.Combine(root, "NuGet.Config");
        var original = File.Exists(config) ? File.ReadAllBytes(config) : null;
        File.WriteAllText(config, "<configuration><packageSources><clear/><add key=\"declared\" value=\"" +
            System.Security.SecurityElement.Escape(Path.Combine(root, ".package-source")) + "\"/></packageSources><fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>");
        Environment.SetEnvironmentVariable("NUGET_PACKAGES", packages);
        return new ConfigLease(config, original);
    }

    // Keep resolver feed overrides out of authored inputs and build outputs.
    private sealed class ConfigLease(string path, byte[]? original) : IDisposable
    {
        public void Dispose()
        {
            if (original is null)
            {
                File.Delete(path);
            }
            else
            {
                File.WriteAllBytes(path, original);
            }
        }
    }
}
