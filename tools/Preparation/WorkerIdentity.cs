using System.Runtime.InteropServices;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

// Execution-host identity is independent of the graph's target framework/RID.
// Equality is intentionally conservative until broader worker pairs are qualified.
internal static class WorkerIdentity
{
    public const string Policy = "darwin-arm64-worker-v1";
    private static readonly string[] SystemTools = OperatingSystem.IsLinux() ? ["/usr/bin/bwrap", "/bin/sh", "/usr/bin/env", "/usr/bin/uname", .. LinuxPlatform.Configuration] : ["/usr/bin/sandbox-exec", "/usr/bin/codesign", "/usr/bin/security", "/bin/sh", "/usr/bin/env", "/usr/bin/sw_vers", "/usr/sbin/sysctl"];
    public static JsonObject Capture(string controller, string bazel, string cwd, bool independent = false)
    {
        if ((!OperatingSystem.IsMacOS() && !OperatingSystem.IsLinux()) || RuntimeInformation.OSArchitecture != Architecture.Arm64 || RuntimeInformation.ProcessArchitecture != Architecture.Arm64)
            throw new PlatformNotSupportedException("Worker policy requires native macOS or Linux ARM64");
        var tools = new JsonObject { ["bazel"] = FileTree.HashRegular(Host.Real(bazel)).Digest };
        foreach (var path in SystemTools) tools[path] = FileTree.HashRegular(Host.Real(path)).Digest;
        return new JsonObject
        {
            ["policy"] = OperatingSystem.IsLinux() ? "linux-arm64-worker-v1" : Policy,
            ["scope"] = independent ? "independent-qualified-workers" : "same-host-experimental",
            ["controllerSdkClosure"] = controller,
            ["execution"] = new JsonObject
            {
                ["os"] = OperatingSystem.IsLinux() ? "Linux" : "macOS",
                ["osBuild"] = OperatingSystem.IsLinux() ? File.ReadAllText("/etc/os-release") : Host.Run("/usr/bin/sw_vers", ["-buildVersion"], cwd).Trim(),
                ["kernel"] = OperatingSystem.IsLinux() ? Host.Run("/usr/bin/uname", ["-srv"], cwd).Trim() : RuntimeInformation.OSDescription,
                ["architecture"] = "Arm64",
                ["cpuModel"] = OperatingSystem.IsLinux() ? "aarch64" : Host.Run("/usr/sbin/sysctl", ["-n", "hw.model"], cwd).Trim(),
                ["cpuBrand"] = OperatingSystem.IsLinux() ? string.Join("\n", File.ReadLines("/proc/cpuinfo").Where(line => line.StartsWith("Features", StringComparison.Ordinal) || line.StartsWith("CPU implementer", StringComparison.Ordinal) || line.StartsWith("CPU part", StringComparison.Ordinal) || line.StartsWith("CPU variant", StringComparison.Ordinal) || line.StartsWith("CPU revision", StringComparison.Ordinal)).Distinct().Order(StringComparer.Ordinal)) : Host.Run("/usr/sbin/sysctl", ["-n", "machdep.cpu.brand_string"], cwd).Trim(),
                ["cpuCount"] = Environment.ProcessorCount
            },
            ["systemTools"] = tools,
            ["environmentPolicy"] = "evaluated-net10-release-env-v1",
            ["hostPolicy"] = OperatingSystem.IsLinux() ? "hashed-ubuntu2204-libraries-reviewed-packages-v1" : "sealed-macos-system-libraries-reviewed-packages-v1"
        };
    }
    public static string Digest(JsonNode worker)
    {
        if (worker["policy"]?.GetValue<string>() is not (Policy or "linux-arm64-worker-v1")) throw new InvalidDataException("Unsupported worker policy");
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
