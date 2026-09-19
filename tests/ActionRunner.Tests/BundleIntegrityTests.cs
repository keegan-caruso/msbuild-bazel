using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using RulesMSBuild;

internal static class BundleIntegrityTests
{
    internal static void Run()
    {
        static string Sha(byte[] value) => Convert.ToHexStringLower(SHA256.HashData(value));
        static Dictionary<string, byte[]> Fixture()
        {
            var files = new Dictionary<string, byte[]>
            {
                ["artifacts/App.dll"] = [1, 2, 3],
                ["results.json"] = JsonSerializer.SerializeToUtf8Bytes(new { key = new string('1', 64), inputs = new string('2', 64), toolchain = new string('3', 64), project = "App/App.csproj" })
            };
            files["artifacts.json"] = JsonSerializer.SerializeToUtf8Bytes(new[] { new { path = "App.dll", size = 3, sha256 = Sha(files["artifacts/App.dll"]) } });
            return files;
        }
        static void Seal(Dictionary<string, byte[]> files) => files["bundle.json"] = JsonSerializer.SerializeToUtf8Bytes(new { schemaVersion = 1, resultsSha256 = Sha(files["results.json"]), artifactsSha256 = Sha(files["artifacts.json"]) });
        var valid = Fixture(); Seal(valid);
        BundleIntegrity.Validate(valid.Keys, name => valid[name]);
        foreach (var invalid in new[] { "bytes", "missing", "extra", "identity", "path", "duplicate" })
        {
            var files = Fixture();
            switch (invalid)
            {
                case "bytes": files["artifacts/App.dll"] = [9]; break;
                case "missing": files.Remove("artifacts/App.dll"); break;
                case "extra": files["nested/undeclared"] = [1]; break;
                case "identity":
                    var result = JsonNode.Parse(files["results.json"])!;
                    result["toolchain"] = "invalid"; files["results.json"] = JsonSerializer.SerializeToUtf8Bytes(result); break;
                case "path":
                    var artifacts = JsonNode.Parse(files["artifacts.json"])!.AsArray();
                    artifacts[0]!["path"] = "../escape"; files["artifacts.json"] = JsonSerializer.SerializeToUtf8Bytes(artifacts); break;
                case "duplicate":
                    var duplicate = JsonNode.Parse(files["artifacts.json"])!.AsArray();
                    duplicate.Add(duplicate[0]!.DeepClone()); files["artifacts.json"] = JsonSerializer.SerializeToUtf8Bytes(duplicate); break;
            }
            Seal(files);
            try
            {
                BundleIntegrity.Validate(files.Keys, name => files[name]);
                throw new InvalidOperationException("Invalid publication accepted: " + invalid);
            }
            catch (InvalidDataException) { }
        }
    }
}
