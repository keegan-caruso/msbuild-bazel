using System.Security.Cryptography;
using System.Text.Json;
using Microsoft.Build.Execution;

namespace RulesMSBuild.ProjectCache;

// A private handoff between the qualifier and the ordinary graph-cache writer.
// It is not a portable MSBuild result-cache file or a replacement cache format.
internal sealed record SeedItem(string Include, Dictionary<string, string> Metadata);
internal sealed record SeedTarget(string Name, SeedItem[] Items);
internal sealed record SeedContext(Dictionary<string, string> Properties, Dictionary<string, string> Items);
internal sealed record SeedProject(string Key, SeedContext Context, string[] RequestedTargets, SeedTarget[] Targets, string[] References);
internal sealed record BuildSeed(int Version, string Root, string Sdk, string SdkDigest,
    Dictionary<string, string> Inputs, Dictionary<string, string> Outputs, SeedProject[] Projects);

internal static class BuildSeedProof
{
    internal const string Base = "/__rules_msbuild_graph";
    internal const string Root = Base + "/output/workspace";
    internal const string Sdk = Base + "/sdk";

    internal static SeedContext Context(ProjectInstance project)
    {
        var properties = project.Properties.ToDictionary(property => property.Name, property => property.EvaluatedValue, StringComparer.Ordinal);
        foreach (var (name, value) in project.GlobalProperties)
        {
            properties.Add("global:" + name, value);
        }
        var items = project.ItemTypes.ToDictionary(type => type, type => Hash(JsonSerializer.Serialize(project.GetItems(type)
            .Select(item => new
            {
                item.EvaluatedInclude,
                Metadata = item.Metadata.OrderBy(pair => pair.Name, StringComparer.Ordinal)
                .ToDictionary(pair => pair.Name, pair => pair.EvaluatedValue, StringComparer.Ordinal)
            }))), StringComparer.Ordinal);
        return new(properties, items);
    }

    internal static string Digest(string path)
    {
        using var stream = File.OpenRead(path);
        return Hash(Convert.ToHexString(SHA256.HashData(stream)) + ":" + (OperatingSystem.IsWindows() ? 0 : (int)File.GetUnixFileMode(path)));
    }

    internal static string TreeDigest(string root) => Hash(JsonSerializer.Serialize(Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories)
        .Order(StringComparer.Ordinal).ToDictionary(path => Path.GetRelativePath(root, path), Digest, StringComparer.Ordinal)));

    internal static string Key(ProjectInstance project) => project.FullPath + "|" + string.Join(";", project.GlobalProperties
        .OrderBy(pair => pair.Key, StringComparer.Ordinal).Select(pair => pair.Key + "=" + pair.Value));

    private static string Hash(string value) => Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(value))).ToLowerInvariant();
}
