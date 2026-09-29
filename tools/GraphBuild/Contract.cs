using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace RulesMSBuild.GraphBuild;

internal sealed record GraphContract(
    int Version,
    string Entry,
    string SdkVersion,
    Dictionary<string, string> Properties,
    string[] SharedInputs,
    Dictionary<string, ProjectContract> Projects);

// Inputs include task reads that evaluation cannot discover. Outputs are owned
// directories relative to the workspace; dependency copies are handled separately.
internal sealed record ProjectContract(string[] Inputs, string[] OutputDirectories,
    bool ReferenceBoundary = false, Dictionary<string, string>? DependencyCopies = null);

internal sealed class ContractFiles(string root, string sdk)
{
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

    internal static string Digest(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexStringLower(SHA256.HashData(stream));
    }

    internal static string Hash(IEnumerable<string> records) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(JsonSerializer.Serialize(records))));

    internal static string TreeDigest(string directory) => Hash(Directory.EnumerateFiles(directory, "*", SearchOption.AllDirectories)
        .Order(StringComparer.Ordinal).Select(path => Path.GetRelativePath(directory, path) + ":" + Digest(path)));
}
