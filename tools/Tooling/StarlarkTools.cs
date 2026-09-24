using System.Runtime.InteropServices;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Tooling;

internal static class StarlarkTools
{
    private static JsonNode Artifact(JsonNode tool)
    {
        var os = OperatingSystem.IsMacOS() ? "Darwin" : OperatingSystem.IsLinux() ? "Linux" : throw new PlatformNotSupportedException();
        var architecture = RuntimeInformation.OSArchitecture == Architecture.Arm64 ? os == "Darwin" ? "arm64" : "aarch64" : "x86_64";
        return tool["platforms"]![os + "-" + architecture]!;
    }

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
            var binary = Path.Combine(root, ".tools/bin", name);
            if (!File.Exists(binary) || Json.Sha(File.ReadAllBytes(binary)) != artifact.String("sha256"))
            {
                Directory.CreateDirectory(Path.GetDirectoryName(binary)!);
                var temporary = binary + "." + Guid.NewGuid().ToString("N");
                try
                {
                    Host.Run("curl", ["--fail", "--location", "--silent", "--show-error", "--retry", "3", "--connect-timeout", "20", "--max-time", "300", artifact.String("url"), "--output", temporary], root);
                    if (Json.Sha(File.ReadAllBytes(temporary)) != artifact.String("sha256"))
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
        var binary = Path.Combine(root, ".tools/bin/buildifier");
        if (!File.Exists(binary) || Json.Sha(File.ReadAllBytes(binary)) != artifact.String("sha256"))
        {
            throw new InvalidDataException("Run bash scripts/tooling.sh setup-starlark");
        }
        return binary;
    }
}
