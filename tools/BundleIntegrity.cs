using System.Security.Cryptography;
using System.Text.Json.Nodes;

namespace RulesMSBuild;

// Shared publication contract: run inside producing actions and at trust boundaries.
internal static class BundleIntegrity
{
    internal static JsonNode Validate(IEnumerable<string> names, Func<string, byte[]> read)
    {
        static string Sha(byte[] bytes) => Convert.ToHexStringLower(SHA256.HashData(bytes));
        static string Text(JsonNode node, string key) => node[key]?.GetValue<string>() ?? throw new InvalidDataException("Missing bundle field: " + key);
        static string Safe(string path) => !string.IsNullOrEmpty(path) && !Path.IsPathRooted(path) && !path.Split('/').Any(part => part is "" or "." or "..") && path.IndexOfAny([':', '\\', '\n', '\r']) < 0
            ? path : throw new InvalidDataException("unsafe workspace path: " + path);
        static void Digest(string value)
        {
            if (value.Length != 64 || value.Any(c => c is not (>= '0' and <= '9' or >= 'a' and <= 'f'))) throw new InvalidDataException("Invalid CAS digest");
        }
        try
        {
            var members = names.ToHashSet(StringComparer.Ordinal);
            var seal = JsonNode.Parse(read("bundle.json"))!;
            var result = JsonNode.Parse(read("results.json"))!;
            var artifacts = JsonNode.Parse(read("artifacts.json"))!.AsArray();
            var version = seal["schemaVersion"]?.GetValue<int>();
            if (version is not (1 or 3) || Text(seal, "resultsSha256") != Sha(read("results.json")) || Text(seal, "artifactsSha256") != Sha(read("artifacts.json")) || artifacts.Count == 0)
                throw new InvalidDataException("Invalid bundle seal");
            var expected = new HashSet<string>(["bundle.json", "results.json", "artifacts.json"], StringComparer.Ordinal);
            var origins = new Dictionary<string, string>(StringComparer.Ordinal);
            if (version == 3)
            {
                if (Text(seal, "packageOriginsSha256") != Sha(read("package-origins.json"))) throw new InvalidDataException("Invalid package origins seal");
                foreach (var origin in JsonNode.Parse(read("package-origins.json"))!.AsObject())
                {
                    var source = Safe(origin.Value!.GetValue<string>());
                    if (source.Split('/').Length < 3) throw new InvalidDataException("Invalid package origin");
                    origins.Add(Safe(origin.Key), source);
                }
                if (origins.Count == 0) throw new InvalidDataException("Empty package origins");
                expected.Add("package-origins.json");
            }
            var logical = new HashSet<string>(StringComparer.Ordinal);
            foreach (var artifact in artifacts)
            {
                var path = Safe(Text(artifact!, "path"));
                if (!logical.Add(path)) throw new InvalidDataException("Duplicate artifact");
                Digest(Text(artifact!, "sha256"));
                if (origins.ContainsKey(path))
                {
                    if (artifact!["size"]!.GetValue<long>() <= 0) throw new InvalidDataException("Invalid package artifact size");
                    continue;
                }
                var name = "artifacts/" + path;
                if (!expected.Add(name) || !members.Contains(name)) throw new InvalidDataException("Invalid artifact bytes");
                var bytes = read(name);
                if (bytes.LongLength != artifact!["size"]!.GetValue<long>() || Sha(bytes) != Text(artifact, "sha256")) throw new InvalidDataException("Invalid artifact bytes");
            }
            if (origins.Keys.Any(path => !logical.Contains(path))) throw new InvalidDataException("Undeclared package origin");
            if (!expected.SetEquals(members)) throw new InvalidDataException("Undeclared bundle member");
            foreach (var key in new[] { "key", "inputs", "toolchain" }) Digest(Text(result, key));
            Safe(Text(result, "project"));
            return result;
        }
        catch (Exception error) when (error is KeyNotFoundException or InvalidOperationException or ArgumentException or NullReferenceException or System.Text.Json.JsonException)
        { throw new InvalidDataException("Invalid bundle metadata", error); }
    }
}
