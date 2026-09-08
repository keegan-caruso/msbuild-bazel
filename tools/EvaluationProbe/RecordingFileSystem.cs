using System.Collections.Concurrent;
using System.Security.Cryptography;
using Microsoft.Build.FileSystem;

internal sealed record Observation(string Operation, string Path, string? Pattern, string? Option, string Result);

internal sealed class RecordingFileSystem : MSBuildFileSystemBase
{
    public ConcurrentQueue<Observation> Observations { get; } = new();

    private T Observe<T>(string operation, string path, Func<T> action, Func<T, string> format, string? pattern = null, string? option = null)
    {
        path = System.IO.Path.GetFullPath(path);
        try
        {
            var result = action();
            Observations.Enqueue(new(operation, path, pattern, option, format(result)));
            return result;
        }
        catch (Exception error) when (error is IOException or UnauthorizedAccessException)
        {
            Observations.Enqueue(new(operation, path, pattern, option, "error:" + error.GetType().Name));
            throw;
        }
    }

    public override bool FileExists(string path) => Observe("file-exists", path, () => base.FileExists(path), value => value ? "true" : "false");
    public override bool DirectoryExists(string path) => Observe("directory-exists", path, () => base.DirectoryExists(path), value => value ? "true" : "false");
    public override bool FileOrDirectoryExists(string path) => Observe("exists", path, () => base.FileOrDirectoryExists(path), value => value ? "true" : "false");
    public override FileAttributes GetAttributes(string path) => Observe("attributes", path, () => base.GetAttributes(path), value => ((int)value).ToString(System.Globalization.CultureInfo.InvariantCulture));
    public override DateTime GetLastWriteTimeUtc(string path) => Observe("mtime", path, () => base.GetLastWriteTimeUtc(path), value => value.Ticks.ToString(System.Globalization.CultureInfo.InvariantCulture));
    public override IEnumerable<string> EnumerateFiles(string path, string searchPattern = "*", SearchOption searchOption = SearchOption.TopDirectoryOnly) =>
        Enumerate("files", path, searchPattern, searchOption, () => base.EnumerateFiles(path, searchPattern, searchOption));
    public override IEnumerable<string> EnumerateDirectories(string path, string searchPattern = "*", SearchOption searchOption = SearchOption.TopDirectoryOnly) =>
        Enumerate("directories", path, searchPattern, searchOption, () => base.EnumerateDirectories(path, searchPattern, searchOption));
    public override IEnumerable<string> EnumerateFileSystemEntries(string path, string searchPattern = "*", SearchOption searchOption = SearchOption.TopDirectoryOnly) =>
        Enumerate("entries", path, searchPattern, searchOption, () => base.EnumerateFileSystemEntries(path, searchPattern, searchOption));

    private string[] Enumerate(string operation, string path, string pattern, SearchOption option, Func<IEnumerable<string>> action) =>
        Observe(operation, path, () => action().ToArray(), value => System.Text.Json.JsonSerializer.Serialize(value), pattern, option.ToString());

    private byte[] Read(string path) => Observe("read", path, () => File.ReadAllBytes(path), value => Convert.ToHexString(SHA256.HashData(value)).ToLowerInvariant());
    public override byte[] ReadFileAllBytes(string path) => Read(path);
    public override TextReader ReadFile(string path) => new StreamReader(new MemoryStream(Read(path)));
    public override string ReadFileAllText(string path)
    {
        using var reader = ReadFile(path);
        return reader.ReadToEnd();
    }
    public override Stream GetFileStream(string path, FileMode mode, FileAccess access, FileShare share)
    {
        if (mode != FileMode.Open || access != FileAccess.Read) throw new InvalidOperationException("evaluation recorder only permits read streams");
        return new MemoryStream(Read(path), writable: false);
    }
}
