using System.Text;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

internal static class TestDeclarations
{
    public static string Write(string workspace, string output, string root, Dictionary<string, JsonNode> nodes, JsonArray tests, string runner)
    {
        Host.Copy(Path.Combine(root, "bazel/graph_test.bzl"), Path.Combine(output, "graph_test.bzl"));
        foreach (var suffix in new[] { ".dll", ".deps.json", ".runtimeconfig.json" }) Host.Copy(Path.ChangeExtension(runner, null) + suffix, Path.Combine(output, "test-runner/TestRunner" + suffix));
        var declarations = new JsonArray(); var seen = new HashSet<string>(StringComparer.Ordinal); var build = new StringBuilder();
        foreach (var test in tests.Select(n => n ?? throw new InvalidDataException("null test declaration")))
        {
            var id = test!.String("node");
            if (!nodes.TryGetValue(id, out var node) || !seen.Add(id)) throw new InvalidDataException("missing or duplicate test node");
            var expected = test.Array("expectedTests").Select(n => n?.GetValue<string>()).ToArray();
            if (expected.Length == 0 || expected.Distinct(StringComparer.Ordinal).Count() != expected.Length || expected.Any(string.IsNullOrEmpty)) throw new InvalidDataException("expectedTests must contain unique test names");
            var data = new List<string>(); var hashes = new JsonObject();
            foreach (var item in test.Array("data"))
            {
                var logical = Host.Safe(item!.GetValue<string>()); var source = Path.Combine(workspace, logical);
                if (!File.Exists(source) || !Host.Within(Host.Real(source), workspace)) throw new InvalidDataException("missing or escaping test data: " + logical);
                if (hashes.ContainsKey(logical)) throw new InvalidDataException("duplicate declared test data");
                var bytes = File.ReadAllBytes(source);
                var target = Path.Combine(output, "test-data", logical); Directory.CreateDirectory(Path.GetDirectoryName(target)!); File.WriteAllBytes(target, bytes);
                data.Add("test-data/" + logical); hashes[logical] = Json.Sha(bytes);
            }
            var directory = Host.Relative(GraphPreparation.Execution(node).String("outputDirectory"));
            var assemblies = node.Array("outputs").Where(n => n!.String("kind") == "assembly").Select(n => n!.String("path")).ToArray();
            if (assemblies.Length != 1 || Path.GetDirectoryName(assemblies[0]) != "workspace/" + directory) throw new InvalidDataException("test node requires exactly one assembly in its runtime output directory");
            build.Append(Starlark.Call("graph_test", new JsonObject
            {
                ["name"] = "test_" + id,
                ["subject"] = ":node_" + id,
                ["project"] = Host.Relative(node.String("project")),
                ["global_properties"] = node["globalProperties"]!.DeepClone(),
                ["runtime_directory"] = directory,
                ["assembly"] = Path.GetFileName(assemblies[0]),
                ["data"] = Json.Strings(data),
                ["data_hashes"] = hashes.DeepClone(),
                ["expected_tests"] = test["expectedTests"]!.DeepClone(),
                ["runner"] = "test-runner/TestRunner.dll",
                ["runner_support"] = Json.Strings(["test-runner/TestRunner.deps.json", "test-runner/TestRunner.runtimeconfig.json"]),
                ["host_identity"] = "host-identity.json",
                ["sdk"] = "@dotnet//:files",
                ["dotnet"] = "@dotnet//:sdk/dotnet",
                ["size"] = "small",
                ["timeout"] = "moderate"
            }));
            declarations.Add(new JsonObject { ["node"] = id, ["target"] = "//:test_" + id, ["dataHashes"] = hashes, ["expectedTests"] = test["expectedTests"]!.DeepClone() });
        }
        Json.Write(Path.Combine(output, "tests.json"), new JsonObject { ["schemaVersion"] = 1, ["tests"] = declarations });
        return build.ToString();
    }
}
