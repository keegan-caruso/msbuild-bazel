using System.IO.Compression;
using System.Security.Cryptography;
using System.Text.Json;
using System.Xml.Linq;

internal sealed record PackageRequest(string Id, string Version, string Archive, string ContentHash, string ArchiveSha256, string Output, bool Generated = false, string? ValidationOutput = null);
internal static class Package
{
    public static void Extract(PackageRequest request)
    {
        var id = Program.Safe(request.Id.ToLowerInvariant());
        var version = Program.Safe(request.Version);
        if (id.Contains('/') || version.Contains('/'))
        {
            throw new InvalidDataException("Invalid package identity");
        }

        if (request.Generated && (request.ContentHash.Length != 0 || request.ArchiveSha256.Length != 0))
        {
            throw new InvalidDataException("Generated packages must not specify acquired archive hashes");
        }

        using var source = new FileStream(request.Archive, FileMode.Open, FileAccess.Read, FileShare.Read);
        var stagedPath = Path.Combine(Path.GetTempPath(), "msbuild-package-" + Guid.NewGuid().ToString("N"));
        var stageOptions = new FileStreamOptions
        {
            Mode = FileMode.CreateNew,
            Access = FileAccess.ReadWrite,
            Share = FileShare.None,
            BufferSize = 81920,
            Options = FileOptions.DeleteOnClose,
        };
        if (!OperatingSystem.IsWindows())
        {
            stageOptions.UnixCreateMode = UnixFileMode.UserRead | UnixFileMode.UserWrite;
        }
        using var staged = new FileStream(stagedPath, stageOptions);
        using var sha256 = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        using var sha512 = IncrementalHash.CreateHash(HashAlgorithmName.SHA512);
        var buffer = new byte[81920];
        int count;
        while ((count = source.Read(buffer)) != 0)
        {
            sha256.AppendData(buffer, 0, count);
            sha512.AppendData(buffer, 0, count);
            staged.Write(buffer, 0, count);
        }
        var contentHash = Convert.ToBase64String(sha512.GetHashAndReset());
        var archiveHash = Convert.ToHexString(sha256.GetHashAndReset()).ToLowerInvariant();
        if (!request.Generated && Convert.FromBase64String(request.ContentHash).Length != 64)
        {
            throw new InvalidDataException("Invalid NuGet content hash");
        }

        if (!request.Generated && !archiveHash.Equals(request.ArchiveSha256, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("Package archive differs from locked archive hash");
        }

        if (!request.Generated && contentHash != request.ContentHash)
        {
            throw new InvalidDataException("Package archive differs from locked content hash");
        }

        Directory.CreateDirectory(request.Output);
        staged.Position = 0;
        using var zip = new ZipArchive(staged, ZipArchiveMode.Read, leaveOpen: true);
        var nuspec = zip.Entries.Single(e => !e.FullName.Contains('/') && e.FullName.EndsWith(".nuspec", StringComparison.OrdinalIgnoreCase));
        using (var stream = nuspec.Open())
        {
            var metadata = XDocument.Load(stream).Root!.Elements().Single(e => e.Name.LocalName == "metadata");
            string Value(string name) => metadata.Elements().Single(e => e.Name.LocalName == name).Value;
            if (!Value("id").Equals(id, StringComparison.OrdinalIgnoreCase) || !NuGet.Versioning.VersionComparer.VersionRelease.Equals(NuGet.Versioning.NuGetVersion.Parse(Value("version")), NuGet.Versioning.NuGetVersion.Parse(version)))
            {
                throw new InvalidDataException("Package identity differs from lock");
            }
        }
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase) { ".nupkg.metadata", id + "." + version + ".nupkg", id + "." + version + ".nupkg.sha512" };
        foreach (var entry in zip.Entries)
        {
            if (entry.FullName.EndsWith('/'))
            {
                continue;
            }

            var relative = Program.Safe(System.Text.RegularExpressions.Regex.Replace(entry.FullName, "/{2,}", "/").Replace("%2B", "+", StringComparison.OrdinalIgnoreCase));
            if (!names.Add(relative))
            {
                throw new InvalidDataException("Duplicate package entry");
            }

            var path = Path.Combine(request.Output, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            using var input = entry.Open();
            using var output = File.Create(path);
            input.CopyTo(output);
        }
        var archive = Path.Combine(request.Output, id + "." + version + ".nupkg");
        staged.Position = 0;
        using (var retained = File.Create(archive))
        {
            staged.CopyTo(retained);
        }
        source.Position = 0;
        if (!Convert.ToHexString(SHA256.HashData(source)).Equals(archiveHash, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("Package archive changed during extraction");
        }
        File.WriteAllText(archive + ".sha512", contentHash);
        File.WriteAllText(Path.Combine(request.Output, ".nupkg.metadata"), JsonSerializer.Serialize(new
        {
            version = 2,
            contentHash,
            source = request.Generated ? "bazel-generated-package" : "bazel-locked-package"
        }));
        if (request.ValidationOutput is not null)
        {
            File.WriteAllText(request.ValidationOutput, JsonSerializer.Serialize(new
            {
                id,
                version,
                archiveSha256 = archiveHash,
                contentHash
            }));
        }
    }
}
