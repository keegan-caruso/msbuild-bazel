using ActionRunner;

namespace NativeCache;

// Preserve NuGet's private logical paths while borrowing immutable Bazel files.
internal sealed class ReadOnlyPackageInputs
{
    private readonly Dictionary<string, string> borrowed = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string> links = new(StringComparer.Ordinal);

    public void Link(string source, string destination, string expectedHash)
    {
        if (OperatingSystem.IsWindows()) throw new InvalidDataException("Borrowed package inputs require Unix read-only files");
        var path = Path.GetFullPath(source);
        const UnixFileMode writes = UnixFileMode.UserWrite | UnixFileMode.GroupWrite | UnixFileMode.OtherWrite;
        if ((File.GetUnixFileMode(path) & writes) != 0) throw new InvalidDataException("Borrowed package input is writable: " + path);
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        File.CreateSymbolicLink(destination, path);
        borrowed[path] = expectedHash;
        links[Path.GetFullPath(destination)] = path;
    }

    public Dictionary<string, string> Aliases(string workspace) => links
        .Where(pair => new FileInfo(pair.Key).LinkTarget == pair.Value)
        .ToDictionary(pair => Path.GetRelativePath(workspace, pair.Key), pair => pair.Value, StringComparer.Ordinal);

    public static void VerifyAlias(string destination, string source)
    {
        if (OperatingSystem.IsWindows()) throw new InvalidDataException("Borrowed package inputs require Unix read-only files");
        const UnixFileMode writes = UnixFileMode.UserWrite | UnixFileMode.GroupWrite | UnixFileMode.OtherWrite;
        if (new FileInfo(destination).LinkTarget != source || (File.GetUnixFileMode(source) & writes) != 0)
            throw new InvalidDataException("Borrowed package alias changed: " + destination);
    }

    public void VerifyUnchanged()
    {
        foreach (var (path, hash) in borrowed)
            if (Files.Hash(path) != hash) throw new InvalidDataException("Borrowed package input changed: " + path);
    }
}
