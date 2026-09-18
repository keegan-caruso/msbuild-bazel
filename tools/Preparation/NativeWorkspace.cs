using System.Text;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

internal sealed class NativeWorkspace(string destination)
{
    private readonly HashSet<string> desired = new(StringComparer.Ordinal);
    private void Write(string relative, byte[] data)
    {
        Host.Safe(relative); var path = Path.Combine(destination, relative); desired.Add(relative);
        if (Host.Real(path) != Path.GetFullPath(path)) throw new InvalidDataException("Linked generated input");
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        if (!File.Exists(path) || !File.ReadAllBytes(path).AsSpan().SequenceEqual(data)) File.WriteAllBytes(path, data);
    }
    private void Copy(string source, string relative) => Write(relative, File.ReadAllBytes(source));
    public void Generate(string repository, string sdk, string plan, string workspace, JsonNode? tests, string? seeds, string[] imports)
    {
        Directory.CreateDirectory(destination);
        var manifest = Json.Read(Path.Combine(plan, "manifest.json")); var entry = Json.Read(Path.Combine(plan, "entry.json")).String("entry");
        var module = "module(name = \"native_msbuild_workflow\")\n\nbazel_dep(name = \"platforms\", version = \"0.0.11\")\n\nlocal_dotnet_sdk = use_repo_rule(\"//:msbuild.bzl\", \"local_dotnet_sdk\")\n" + Starlark.Call("local_dotnet_sdk", new JsonObject { ["name"] = "dotnet", ["path"] = sdk, ["external_imports"] = Json.Strings(imports) });
        Write("MODULE.bazel", Encoding.UTF8.GetBytes(module));
        Copy(Path.Combine(repository, "bazel/native.MODULE.bazel.lock"), "MODULE.bazel.lock");
        foreach (var path in FileTree.Files(Path.Combine(plan, "src"))) Copy(path, "src/" + Path.GetRelativePath(Path.Combine(plan, "src"), path));
        foreach (var name in new[] { "restore.json", "manifest.json" }) Copy(Path.Combine(plan, name), name);
        foreach (var name in new[] { "msbuild.bzl", "native_cache.bzl", "native_test.bzl", "input_paths.bzl" }) Copy(Path.Combine(repository, "bazel", name), name);
        foreach (var name in new[] { "NativeProjectCache", "TestRunner" })
            foreach (var suffix in new[] { ".dll", ".deps.json", ".runtimeconfig.json" }) Copy(Path.Combine(repository, "tools", name, "bin/Release/net10.0", name + suffix), "runner/" + name + suffix);
        if (seeds is not null && Directory.Exists(seeds))
            foreach (var bundle in Directory.GetDirectories(seeds))
            {
                try
                {
                    FileTree.Snapshot(bundle);
                    var files = FileTree.Files(bundle).ToDictionary(p => Path.GetRelativePath(bundle, p), File.ReadAllBytes, StringComparer.Ordinal);
                    var result = RemoteCache.ValidateBundle(files);
                    if (result.String("key") != Path.GetFileName(bundle) || result.String("toolchain") != manifest.String("toolchain") || manifest["projects"]?[result.String("project")]?["identity"]?.GetValue<string>() != result.String("inputs")) continue;
                    foreach (var (name, data) in files) Write("seeds/" + result.String("key") + "/" + name, data);
                }
                catch (Exception error) when (error is IOException or InvalidDataException or System.Text.Json.JsonException or KeyNotFoundException) { }
            }
        var build = "load(\":native_cache.bzl\", \"msbuild_native_cache\")\n";
        if (tests is not null) build += "load(\":native_test.bzl\", \"native_test\")\n";
        build += Starlark.Call("msbuild_native_cache", new JsonObject
        {
            ["name"] = "build",
            ["project"] = entry,
            ["srcs"] = Json.Strings(desired.Where(p => p.StartsWith("src/", StringComparison.Ordinal)).Order(StringComparer.Ordinal)),
            ["seeds"] = Json.Strings(desired.Where(p => p.StartsWith("seeds/", StringComparison.Ordinal)).Order(StringComparer.Ordinal)),
            ["manifest"] = "manifest.json",
            ["restore"] = "restore.json",
            ["runner"] = "runner/NativeProjectCache.dll",
            ["runner_support"] = Json.Strings(["runner/NativeProjectCache.deps.json", "runner/NativeProjectCache.runtimeconfig.json"]),
            ["sdk"] = "@dotnet//:files",
            ["dotnet"] = "@dotnet//:sdk/dotnet"
        });
        if (tests is not null)
        {
            var data = new JsonArray(); var hashes = new JsonObject();
            foreach (var item in tests.Array("data"))
            {
                var name = Host.Safe(item!.GetValue<string>()); var path = Path.Combine(workspace, name);
                if (!Host.Within(Host.Real(path), workspace) || hashes.ContainsKey(name)) throw new InvalidDataException("Missing, escaping or duplicate test data");
                var bytes = File.ReadAllBytes(path); hashes[name] = Json.Sha(bytes); Write("test-data/" + name, bytes); data.Add("test-data/" + name);
            }
            build += Starlark.Call("native_test", new JsonObject
            {
                ["name"] = "test",
                ["subject"] = ":build",
                ["project"] = entry,
                ["global_properties"] = new JsonObject { ["configuration"] = "Release", ["targetframework"] = "net10.0" },
                ["native_inputs"] = manifest["projects"]![entry]!["identity"]!.DeepClone(),
                ["native_toolchain"] = manifest["toolchain"]!.DeepClone(),
                ["runtime_directory"] = Path.Combine(Path.GetDirectoryName(entry)!, "bin/Release/net10.0"),
                ["assembly"] = Path.GetFileNameWithoutExtension(entry) + ".dll",
                ["data"] = data,
                ["data_hashes"] = hashes,
                ["expected_tests"] = tests["expectedTests"]!.DeepClone(),
                ["runner"] = "runner/TestRunner.dll",
                ["runner_support"] = Json.Strings(["runner/TestRunner.deps.json", "runner/TestRunner.runtimeconfig.json"]),
                ["host_identity"] = "manifest.json",
                ["sdk"] = "@dotnet//:files",
                ["dotnet"] = "@dotnet//:sdk/dotnet",
                ["size"] = "small",
                ["timeout"] = "moderate"
            });
        }
        Write("BUILD.bazel", Encoding.UTF8.GetBytes(build));
        var receipt = Path.Combine(destination, ".owned.json");
        if (File.Exists(receipt))
            foreach (var name in Json.Read(receipt).AsArray().Select(n => Host.Safe(n!.GetValue<string>())))
                if (!desired.Contains(name))
                {
                    var path = Path.Combine(destination, name); if (Host.Real(path) != path) throw new InvalidDataException("Linked stale generated input"); File.Delete(path);
                }
        FileTree.Atomic(receipt, Json.Strings(desired.Order(StringComparer.Ordinal)));
    }
}
