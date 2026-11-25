using System.Runtime.InteropServices;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Tooling;

internal static class StarlarkTools
{
    private static JsonNode Artifact(JsonNode tool)
    {
        var platform = RuntimeInformation.OSArchitecture switch
        {
            Architecture.X64 when OperatingSystem.IsLinux() => "Linux-x86_64",
            Architecture.Arm64 when OperatingSystem.IsLinux() => "Linux-aarch64",
            Architecture.Arm64 when OperatingSystem.IsMacOS() => "Darwin-arm64",
            Architecture.X64 when OperatingSystem.IsWindows() => "Windows-x86_64",
            _ => throw new PlatformNotSupportedException(RuntimeInformation.RuntimeIdentifier)
        };
        return tool["platforms"]![platform]!;
    }

    private static string Binary(string root, string name) =>
        Path.Combine(root, ".tools/bin", OperatingSystem.IsWindows() ? name + ".exe" : name);

    internal static void Setup(string root)
    {
        var tools = Json.Read(Path.Combine(root, "scripts/starlark-tools.json"));
        if (tools["buildifier"]!.String("version") != tools["buildozer"]!.String("version"))
        {
            throw new InvalidDataException("Buildifier and Buildozer releases must match");
        }
        foreach (var name in new[] { "buildifier", "buildozer" })
        {
            var tool = tools[name]!;
            var artifact = Artifact(tool);
            var binary = Binary(root, name);
            if (!File.Exists(binary) || Json.FileSha256(binary) != artifact.String("sha256"))
            {
                Directory.CreateDirectory(Path.GetDirectoryName(binary)!);
                var temporary = binary + "." + Guid.NewGuid().ToString("N");
                try
                {
                    Host.Run("curl", ["--fail", "--location", "--silent", "--show-error", "--retry", "3", "--connect-timeout", "20", "--max-time", "300", artifact.String("url"), "--output", temporary], root);
                    if (Json.FileSha256(temporary) != artifact.String("sha256"))
                    {
                        throw new InvalidDataException(name + " checksum mismatch");
                    }
                    if (!OperatingSystem.IsWindows())
                    {
                        File.SetUnixFileMode(temporary, (UnixFileMode)493);
                    }
                    File.Move(temporary, binary, true);
                }
                finally { File.Delete(temporary); }
            }
            Console.WriteLine("Verified " + name + " " + tool.String("version"));
        }
    }

    internal static string Buildifier(string root)
    {
        var artifact = Artifact(Json.Read(Path.Combine(root, "scripts/starlark-tools.json"))["buildifier"]!);
        var binary = Binary(root, "buildifier");
        if (!File.Exists(binary) || Json.FileSha256(binary) != artifact.String("sha256"))
        {
            throw new InvalidDataException("Run bash scripts/tooling.sh setup-starlark");
        }
        return binary;
    }
}
