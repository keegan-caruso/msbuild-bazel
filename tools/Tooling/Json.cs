using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Tooling;

internal static class Json
{
    public static string String(this JsonNode? node, string key) => node?[key]?.GetValue<string>() ?? throw new InvalidDataException("Missing string: " + key);
    public static string FileSha256(string path)
    {
        using var input = File.OpenRead(path);
        return Convert.ToHexStringLower(SHA256.HashData(input));
    }
    public static JsonNode Read(string path) => JsonNode.Parse(File.ReadAllText(path)) ?? throw new InvalidDataException("Empty JSON: " + path);
}
