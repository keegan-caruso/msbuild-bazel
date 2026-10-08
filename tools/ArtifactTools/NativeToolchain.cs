using System.Formats.Tar;
using System.IO.Compression;
using System.Security.Cryptography;

internal sealed record NativeToolchainRequest(string Archive, string ArchiveSha256, string Output);

internal static class NativeToolchain
{
    internal static void Extract(NativeToolchainRequest request)
    {
        if (request.ArchiveSha256.Length != 64 || !request.ArchiveSha256.All(Uri.IsHexDigit))
        {
            throw new InvalidDataException("Invalid native toolchain archive SHA-256");
        }

        using (var archive = File.OpenRead(request.Archive))
        {
            var actual = Convert.ToHexString(SHA256.HashData(archive)).ToLowerInvariant();
            if (!actual.Equals(request.ArchiveSha256, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Native toolchain archive differs from locked SHA-256");
            }
        }

        Directory.CreateDirectory(request.Output);
        using var input = File.OpenRead(request.Archive);
        using var gzip = new GZipStream(input, CompressionMode.Decompress);
        TarFile.ExtractToDirectory(gzip, request.Output, overwriteFiles: false);
        if (!Directory.Exists(Path.Combine(request.Output, "usr")) || !Directory.Exists(Path.Combine(request.Output, "etc")))
        {
            throw new InvalidDataException("Native toolchain archive must contain usr and etc directories");
        }
    }
}
