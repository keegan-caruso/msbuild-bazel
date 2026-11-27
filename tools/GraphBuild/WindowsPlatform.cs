using System.Runtime.InteropServices;
using System.Runtime.Versioning;

namespace RulesMSBuild.GraphBuild;

internal static class WindowsPlatform
{
    [SupportedOSPlatformGuard("windows")]
    internal static bool IsNative => OperatingSystem.IsWindows() && Supports(RuntimeInformation.OSArchitecture, RuntimeInformation.ProcessArchitecture);

    internal static bool Supports(Architecture operatingSystem, Architecture process) =>
        operatingSystem == process && operatingSystem is Architecture.X64 or Architecture.Arm64;
}
