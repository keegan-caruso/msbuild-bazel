using System.Security.Cryptography;
using System.Text.Json;

namespace RulesMSBuild.GraphBuild;

internal sealed record GraphContract(
    int Version,
    string Entry,
    string SdkVersion,
    Dictionary<string, string> Properties,
    string[] SharedInputs,
    Dictionary<string, ProjectContract> Projects,
    Dictionary<string, string>? DefinitionDigests = null, string[]? Entries = null, string[]? PackageDigests = null, Dictionary<string, string>? ToolProperties = null, RestoreContract? Restore = null, string[]? InputDirectories = null, string[]? TemporaryDirectories = null, Dictionary<string, Dictionary<string, string>>? EntryProperties = null);

internal sealed record RestoreContract(string[] Inputs, string[] Outputs);

// Inputs include task reads that evaluation cannot discover. Outputs are owned
// directories or required files relative to the workspace; dependency copies are handled separately.
internal sealed record ProjectContract(string[] Inputs, string[] OutputDirectories,
    bool ReferenceBoundary = false, Dictionary<string, string>? DependencyCopies = null,
    ProjectConfiguration[]? Configurations = null, string[]? OutputFiles = null, string[]? ImplementationDependencies = null, string? CompilerReference = null, Dictionary<string, string>? CompilerReferences = null, string[]? ReplayOmissions = null);

// Selectors match global properties, including an empty value for an absent
// property (for example the outer node of a multi-targeted project).
internal sealed record ProjectConfiguration(Dictionary<string, string> Properties,
    string[] Inputs, string[] OutputDirectories, bool ReferenceBoundary = false,
    Dictionary<string, string>? DependencyCopies = null, string[]? OutputFiles = null, string[]? ImplementationDependencies = null, string? CompilerReference = null, Dictionary<string, string>? CompilerReferences = null, string[]? ReplayOmissions = null);

internal sealed class ContractFiles(string root, string sdk)
{
    private static readonly JsonSerializerOptions SmallHashOptions = new() { DefaultBufferSize = 256 };

    internal string Root { get; } = Path.TrimEndingDirectorySeparator(Path.GetFullPath(root));
    internal string Sdk { get; } = Path.TrimEndingDirectorySeparator(Path.GetFullPath(sdk));
    internal string Normalize(string value) => value.Replace(Root, "/_/workspace", StringComparison.Ordinal)
        .Replace(Sdk, "/_/sdk", StringComparison.Ordinal);

    internal string Resolve(string relative)
    {
        if (Path.IsPathRooted(relative) || relative.Contains('\\') || relative.Split('/').Any(p => p is "" or "." or ".."))
        {
            throw new InvalidDataException("Expected a workspace-relative path: " + relative);
        }
        var path = Path.Combine(Root, relative);
        for (var current = path; current != Root; current = Path.GetDirectoryName(current)!)
        {
            if (new FileInfo(current).LinkTarget is not null || new DirectoryInfo(current).LinkTarget is not null)
            {
                throw new InvalidDataException("Symlinks are not supported in graph contracts: " + relative);
            }
        }
        return path;
    }

    // One validation pass checks shared ancestors once. Do not retain this set
    // across execution: final verification must discover newly introduced links.
    internal Dictionary<string, string> ResolveInputs(IEnumerable<string> relatives)
    {
        var checkedPaths = new HashSet<string>(StringComparer.Ordinal) { Root };
        var paths = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var relative in relatives.Distinct(StringComparer.Ordinal))
        {
            if (Path.IsPathRooted(relative) || relative.Contains('\\') || relative.Split('/').Any(p => p is "" or "." or ".."))
            {
                throw new InvalidDataException("Expected a workspace-relative path: " + relative);
            }
            var path = Path.Combine(Root, relative);
            for (var current = path; checkedPaths.Add(current); current = Path.GetDirectoryName(current)!)
            {
                if (new FileInfo(current).LinkTarget is not null || new DirectoryInfo(current).LinkTarget is not null)
                {
                    throw new InvalidDataException("Symlinks are not supported in graph contracts: " + relative);
                }
            }
            paths.Add(relative, path);
        }
        return paths;
    }

    internal static string Digest(string path)
    {
        using var timing = GraphProfile.Measure("fileHash", GraphProfile.Enabled ? new FileInfo(path).Length : 0);
        using var stream = File.OpenRead(path);
        return Convert.ToHexStringLower(SHA256.HashData(stream));
    }

    internal static string InputDigest(string path) => Hash([Digest(path), OperatingSystem.IsWindows() ? "" :
        ((int)(File.GetUnixFileMode(path) & (UnixFileMode.UserExecute | UnixFileMode.GroupExecute | UnixFileMode.OtherExecute))).ToString(System.Globalization.CultureInfo.InvariantCulture)]);

    internal static string Hash(IEnumerable<string> records)
    {
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        using var stream = new HashStream(hash);
        // Preserve the JSON fingerprint format without materializing its string
        // and UTF-8 byte array. Small buffers also serve two-record input digests.
        JsonSerializer.Serialize(stream, records,
            records.TryGetNonEnumeratedCount(out var count) && count <= 2 ? SmallHashOptions : null);
        return Convert.ToHexStringLower(hash.GetHashAndReset());
    }

    internal static string TreeDigest(string directory, int parallelism = 1)
    {
        var paths = Directory.EnumerateFiles(directory, "*", SearchOption.AllDirectories).Order(StringComparer.Ordinal);
        string Record(string path) => Path.GetRelativePath(directory, path) + ":" + InputDigest(path);
        return Hash(parallelism == 1 ? paths.Select(Record) : paths.AsParallel().AsOrdered()
            .WithDegreeOfParallelism(Math.Min(Environment.ProcessorCount, parallelism)).Select(Record));
    }

    private sealed class HashStream(IncrementalHash hash) : Stream
    {
        public override bool CanRead => false;
        public override bool CanSeek => false;
        public override bool CanWrite => true;
        public override long Length => throw new NotSupportedException();
        public override long Position
        {
            get => throw new NotSupportedException();
            set => throw new NotSupportedException();
        }

        public override void Write(byte[] buffer, int offset, int count) => hash.AppendData(buffer, offset, count);
        public override void Write(ReadOnlySpan<byte> buffer) => hash.AppendData(buffer);
        public override void Flush()
        {
        }
        public override int Read(byte[] buffer, int offset, int count) => throw new NotSupportedException();
        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();
        public override void SetLength(long value) => throw new NotSupportedException();
    }
}
