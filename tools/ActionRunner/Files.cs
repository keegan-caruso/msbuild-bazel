using System.Security.Cryptography;

namespace ActionRunner;

internal static class Files
{
    private const UnixFileMode Executable = UnixFileMode.UserExecute | UnixFileMode.GroupExecute | UnixFileMode.OtherExecute;
    private const UnixFileMode DefaultFileMode = UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.GroupRead | UnixFileMode.OtherRead;

    public static string Hash(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexStringLower(SHA256.HashData(stream));
    }

    public static void Copy(string source, string destination)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        File.Copy(source, destination, overwrite: true);
        if (!OperatingSystem.IsWindows())
            File.SetUnixFileMode(destination, File.GetUnixFileMode(source));
    }

    public static void CopyTree(string source, string destination)
    {
        Directory.CreateDirectory(destination);
        foreach (var file in Directory.EnumerateFiles(source, "*", SearchOption.AllDirectories))
            Copy(file, Path.Combine(destination, Path.GetRelativePath(source, file)));
    }

    public static bool ValidRelativePath(string path) =>
        !string.IsNullOrEmpty(path) && !Path.IsPathRooted(path) && !path.Contains('\\') &&
        path.Split('/').All(part => part is not ".." and not "." and not "");

    public static void Verify(string path, long size, string hash, string error)
    {
        if (!File.Exists(path))
            throw new InvalidDataException(error);
        // Bazel presents inputs as symlinks; stream length measures the payload, not the link itself.
        using var stream = File.OpenRead(path);
        if (stream.Length != size || Convert.ToHexStringLower(SHA256.HashData(stream)) != hash)
            throw new InvalidDataException(error);
    }

    public static void NormalizeTree(string root)
    {
        foreach (var path in Directory.EnumerateFileSystemEntries(root, "*", SearchOption.AllDirectories)
                     .OrderDescending(StringComparer.Ordinal))
        {
            var directory = Directory.Exists(path);
            if (!OperatingSystem.IsWindows())
            {
                var executable = directory || (File.GetUnixFileMode(path) & Executable) != 0;
                File.SetUnixFileMode(path, DefaultFileMode | (executable ? Executable : 0));
            }
            if (directory) Directory.SetLastWriteTimeUtc(path, DateTime.UnixEpoch);
            else File.SetLastWriteTimeUtc(path, DateTime.UnixEpoch);
        }
        Directory.SetLastWriteTimeUtc(root, DateTime.UnixEpoch);
    }
}
