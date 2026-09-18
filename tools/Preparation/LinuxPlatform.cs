using System.Diagnostics;
using System.Runtime.InteropServices;

namespace RulesMSBuild.Preparation;

// Deliberately narrow first Linux lane: the pinned setup SDK on Ubuntu ARM64.
internal static class LinuxPlatform
{
    public const string Sdk = "/opt/rules_msbuild-toolchain/.tools/dotnet";
    public static readonly string[] Libraries = ["/usr/lib", "/etc/ssl"];
    public static readonly string[] Configuration = ["/etc/os-release", "/etc/ld.so.cache", "/etc/ssl/openssl.cnf"];
    public static void Require(string sdk)
    {
        if (!OperatingSystem.IsLinux() || RuntimeInformation.OSArchitecture != Architecture.Arm64 || RuntimeInformation.ProcessArchitecture != Architecture.Arm64 || sdk != Sdk || !File.Exists("/usr/bin/bwrap") || (!File.ReadAllText("/etc/os-release").Contains("VERSION_ID=\"22.04\"", StringComparison.Ordinal) || !File.ReadAllText("/etc/os-release").Contains("ID=ubuntu", StringComparison.Ordinal)))
            throw new InvalidDataException("Unqualified Linux discovery host/toolchain");
    }
    public static ProcessStartInfo Discovery(IEnumerable<string> roots, string output, string workspace)
    {
        var start = new ProcessStartInfo("/usr/bin/bwrap") { WorkingDirectory = workspace, RedirectStandardOutput = true, RedirectStandardError = true };
        void Add(params string[] args) { foreach (var arg in args) start.ArgumentList.Add(arg); }
        Add("--die-with-parent", "--unshare-all", "--new-session", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp");
        foreach (var path in roots.Concat(Libraries).Distinct(StringComparer.Ordinal)) Add("--ro-bind", path, path);
        foreach (var path in Configuration) Add("--ro-bind", Host.Real(path), path);
        Add("--symlink", "usr/lib", "/lib", "--bind", output, output, "--chdir", workspace, "--");
        return start;
    }
}
