using System.Formats.Tar;
using System.Runtime.Versioning;

internal static class NativeToolchainArchive
{
    [SupportedOSPlatform("linux")]
    internal static void Write(string root, string output)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
        using var stream = File.Create(output);
        using var writer = new TarWriter(stream, TarEntryFormat.Ustar);
        void Add(string directory)
        {
            foreach (var path in Directory.EnumerateFileSystemEntries(directory).Order(StringComparer.Ordinal))
            {
                var name = Path.GetRelativePath(root, path).Replace(Path.DirectorySeparatorChar, '/');
                var info = new FileInfo(path);
                var link = info.LinkTarget;
                var isDirectory = link is null && Directory.Exists(path);
                var entry = new UstarTarEntry(link is not null ? TarEntryType.SymbolicLink : isDirectory ? TarEntryType.Directory : TarEntryType.RegularFile, name)
                {
                    Uid = 0,
                    Gid = 0,
                    UserName = "",
                    GroupName = "",
                    ModificationTime = DateTimeOffset.UnixEpoch,
                    Mode = link is null ? File.GetUnixFileMode(path) : (UnixFileMode)0x1ff
                };
                if (link is not null)
                {
                    entry.LinkName = link;
                    writer.WriteEntry(entry);
                }
                else if (isDirectory)
                {
                    writer.WriteEntry(entry);
                    Add(path);
                }
                else
                {
                    using var data = File.OpenRead(path);
                    entry.DataStream = data;
                    writer.WriteEntry(entry);
                }
            }
        }
        Add(root);
    }
}
