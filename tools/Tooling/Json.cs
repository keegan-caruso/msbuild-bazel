using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Tooling;

internal static class Json
{
    public static string String(this JsonNode? node, string key) => node?[key]?.GetValue<string>() ?? throw new InvalidDataException("Missing string: " + key);
    public static string Sha(byte[] value) => Convert.ToHexStringLower(SHA256.HashData(value));
    public static JsonNode Read(string path) => JsonNode.Parse(File.ReadAllText(path)) ?? throw new InvalidDataException("Empty JSON: " + path);
}
