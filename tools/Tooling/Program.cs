using System.Runtime.InteropServices;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Tooling;

internal static class Program
{
    public static int Main(string[] args)
    {
        try
        {
            Run(args);
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error.Message); return 1; }
    }
    private static void Run(string[] args)
    {
        if (args.Length < 2)
        {
            throw new ArgumentException("tooling <repository> <check|setup-starlark>");
        }

        var root = Host.Real(args[0]);
        var command = args[1];
        var pins = Json.Read(Path.Combine(root, "scripts/toolchains.json"));
        var version = Json.Read(Path.Combine(root, "global.json"))["sdk"]!.String("version");
        if (pins["dotnet"]!.String("version") != version || pins["bazel"]!.String("version") != File.ReadAllText(Path.Combine(root, ".bazelversion")).Trim())
        {
            throw new InvalidDataException("Toolchain pins differ");
        }

        var shellPins = File.ReadAllText(Path.Combine(root, "scripts/toolchain-pins.sh"));
        foreach (var name in new[] { "dotnet", "bazel" })
        {
            foreach (var arch in new[] { "x64", "arm64" })
            {
                var pin = pins[name]!;
                var platform = pin["platforms"]?["linux-" + arch];
                foreach (var field in new[] { "version", "url", "sha256" })
                {
                    var value = (platform?[field] ?? pin[field])!.GetValue<string>();
                    if (!shellPins.Contains(name + "_" + field + "=" + value + "\n", StringComparison.Ordinal))
                    {
                        throw new InvalidDataException("Bootstrap pin differs from JSON: " + name + " " + field);
                    }
                }
                Digest((platform?["sha256"] ?? pin["sha256"])!.GetValue<string>());
                if (!(platform?["url"] ?? pin["url"])!.GetValue<string>().StartsWith("https://", StringComparison.Ordinal))
                {
                    throw new InvalidDataException("HTTPS download required");
                }
            }
        }

        var starlark = Json.Read(Path.Combine(root, "scripts/starlark-tools.json"))["buildifier"]!;
        var os = OperatingSystem.IsMacOS() ? "Darwin" : OperatingSystem.IsLinux() ? "Linux" : throw new PlatformNotSupportedException();
        var architecture = RuntimeInformation.OSArchitecture == Architecture.Arm64 ? os == "Darwin" ? "arm64" : "aarch64" : "x86_64";
        var artifact = starlark["platforms"]![os + "-" + architecture]!;
        var binary = Path.Combine(root, ".tools/bin/buildifier");
        if (command == "setup-starlark")
        {
            if (!File.Exists(binary) || Json.Sha(File.ReadAllBytes(binary)) != artifact.String("sha256"))
            {
                Directory.CreateDirectory(Path.GetDirectoryName(binary)!);
                var temporary = binary + "." + Guid.NewGuid().ToString("N");
                try
                {
                    Host.Run("curl", ["--fail", "--location", "--silent", "--show-error", "--retry", "3", "--connect-timeout", "20", "--max-time", "300", artifact.String("url"), "--output", temporary], root);
                    if (Json.Sha(File.ReadAllBytes(temporary)) != artifact.String("sha256"))
                    {
                        throw new InvalidDataException("Buildifier checksum mismatch");
                    }

                    if (!OperatingSystem.IsWindows())
                    {
                        File.SetUnixFileMode(temporary, (UnixFileMode)493);
                    }

                    File.Move(temporary, binary, true);
                }
                finally { File.Delete(temporary); }
            }
            Console.WriteLine("Verified Buildifier " + starlark.String("version"));
            return;
        }
        if (command != "check")
        {
            throw new ArgumentException("Unknown tooling command");
        }

        var sdk = Environment.GetEnvironmentVariable("DOTNET_ROOT") ?? Path.Combine(root, ".tools/dotnet");
        if (Host.Run(Path.Combine(sdk, "dotnet"), ["--version"], root).Trim() != version)
        {
            throw new InvalidDataException("SDK version differs");
        }

        var bazel = Environment.GetEnvironmentVariable("RULES_MSBUILD_BAZEL") ?? Path.Combine(root, ".tools/bin/bazel");
        var actual = Host.Run(bazel, ["--batch", "version", "--gnu_format"], root).Trim();
        var expected = "bazel " + (Environment.GetEnvironmentVariable("RULES_MSBUILD_BAZEL_VERSION") ?? pins["bazel"]!.String("version"));
        if (actual != expected && actual != expected + "- (@non-git)")
        {
            throw new InvalidDataException("Bazel version differs: " + actual);
        }

        if (Environment.GetEnvironmentVariable("RULES_MSBUILD_CONTAINER_PREBUILT") == "1")
        {
            foreach (var name in new[] { "dotnet", "bazel" })
            {
                var pin = pins[name]!;
                var hash = pin["platforms"]?["linux-" + (RuntimeInformation.OSArchitecture == Architecture.Arm64 ? "arm64" : "x64")]?["sha256"] ?? pin["sha256"];
                var stamp = name == "dotnet" ? Path.Combine(Path.GetDirectoryName(sdk)!, "dotnet.sha256") : Path.Combine(Path.GetDirectoryName(Path.GetDirectoryName(bazel))!, "bazel.sha256");
                if (File.ReadAllText(stamp).Trim() != hash!.GetValue<string>())
                {
                    throw new InvalidDataException("Prebuilt tool pin differs");
                }
            }
        }

        if (args.Skip(2).Contains("--toolchain-only"))
        {
            Console.WriteLine("Toolchain checks passed");
            return;
        }
        if (!File.Exists(binary) || Json.Sha(File.ReadAllBytes(binary)) != artifact.String("sha256"))
        {
            throw new InvalidDataException("Run bash scripts/tooling.sh setup-starlark");
        }

        IEnumerable<string> files;
        bool IsStarlark(string path) => path.EndsWith(".bzl", StringComparison.Ordinal) || Path.GetFileName(path) is "BUILD" or "BUILD.bazel" or "MODULE.bazel";
        if (Path.Exists(Path.Combine(root, ".git")))
        {
            files = Host.Run("git", ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], root).Split('\0', StringSplitOptions.RemoveEmptyEntries).Where(IsStarlark).Select(p => Path.Combine(root, p));
        }
        else
        {
            files = Enumerate(root).Where(IsStarlark);
        }

        var selected = files.Distinct().Order(StringComparer.Ordinal).ToArray();
        if (selected.Length == 0)
        {
            throw new InvalidDataException("No Starlark files found");
        }

        Host.Run(binary, new[] { "-mode=check", "-lint=warn" }.Concat(selected), root);
        Console.WriteLine("Toolchain and Starlark checks passed");
    }
    private static void Digest(string value)
    {
        if (value.Length != 64 || !value.All(char.IsAsciiHexDigitLower))
        {
            throw new InvalidDataException("Invalid tool digest");
        }
    }
    private static IEnumerable<string> Enumerate(string root)
    {
        foreach (var path in Directory.GetFileSystemEntries(root))
        {
            FileSystemInfo info = Directory.Exists(path) ? new DirectoryInfo(path) : new FileInfo(path);
            if (info.LinkTarget is not null)
            {
                continue;
            }

            if (!Directory.Exists(path))
            {
                yield return path;
                continue;
            }
            if (Path.GetFileName(path) is ".git" or ".tools" or ".cache" or "artifacts" or "bin" or "obj" or "__pycache__" || Path.GetFileName(path).StartsWith("bazel-", StringComparison.Ordinal))
            {
                continue;
            }

            foreach (var file in Enumerate(path))
            {
                yield return file;
            }
        }
    }
}
