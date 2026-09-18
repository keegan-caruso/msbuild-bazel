using System.Runtime.InteropServices;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

// Execution-host identity is independent of the graph's target framework/RID.
// Equality is intentionally conservative until broader worker pairs are qualified.
internal static class WorkerIdentity
{
    public const string Policy = "darwin-arm64-worker-v1";
    private static readonly string[] SystemTools = ["/usr/bin/sandbox-exec", "/usr/bin/codesign", "/usr/bin/security", "/bin/sh", "/usr/bin/env", "/usr/bin/sw_vers", "/usr/sbin/sysctl"];
    public static JsonObject Capture(string controller, string bazel, string cwd, bool independent = false)
    {
        if (!OperatingSystem.IsMacOS() || RuntimeInformation.OSArchitecture != Architecture.Arm64 || RuntimeInformation.ProcessArchitecture != Architecture.Arm64)
            throw new PlatformNotSupportedException("Worker policy requires native macOS ARM64");
        var tools = new JsonObject { ["bazel"] = FileTree.HashRegular(Host.Real(bazel)).Digest };
        foreach (var path in SystemTools) tools[path] = FileTree.HashRegular(Host.Real(path)).Digest;
        return new JsonObject
        {
            ["policy"] = Policy,
            ["scope"] = independent ? "independent-qualified-workers" : "same-host-experimental",
            ["controllerSdkClosure"] = controller,
            ["execution"] = new JsonObject
            {
                ["os"] = "macOS",
                ["osBuild"] = Host.Run("/usr/bin/sw_vers", ["-buildVersion"], cwd).Trim(),
                ["kernel"] = RuntimeInformation.OSDescription,
                ["architecture"] = "Arm64",
                ["cpuModel"] = Host.Run("/usr/sbin/sysctl", ["-n", "hw.model"], cwd).Trim(),
                ["cpuBrand"] = Host.Run("/usr/sbin/sysctl", ["-n", "machdep.cpu.brand_string"], cwd).Trim(),
                ["cpuCount"] = Environment.ProcessorCount
            },
            ["systemTools"] = tools,
            ["environmentPolicy"] = "evaluated-net10-release-env-v1",
            ["hostPolicy"] = "sealed-macos-system-libraries-reviewed-packages-v1"
        };
    }
    public static string Digest(JsonNode worker)
    {
        if (worker["policy"]?.GetValue<string>() != Policy) throw new InvalidDataException("Unsupported worker policy");
        RemoteCache.Digest(worker.String("controllerSdkClosure"));
        return Json.Digest(worker);
    }
    public static void RequireCompatible(JsonNode? producer, JsonNode consumer)
    {
        if (producer is null) throw new InvalidDataException("Snapshot has no compatible-worker identity");
        if (Digest(producer) != Digest(consumer))
        {
            var changed = producer.AsObject().Select(p => p.Key).Union(consumer.AsObject().Select(p => p.Key)).Where(k => !JsonNode.DeepEquals(producer[k], consumer[k]));
            throw new InvalidDataException("Incompatible worker: " + string.Join(", ", changed));
        }
    }
}
