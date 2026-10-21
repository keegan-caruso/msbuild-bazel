using System.Diagnostics;
using System.Reflection;

namespace RulesMSBuild.ProjectSync;

// Each invocation gets private mounts at identical paths. Restore diagnostics,
// generated files and opaque SDK artifacts can retain paths without rebasing bytes.
internal static class QualificationSandbox
{
    internal const string Base = "/__rules_msbuild_sync";
    internal static bool Inside => Environment.GetEnvironmentVariable("RULES_MSBUILD_SYNC_SANDBOX") == "1" &&
        Directory.GetCurrentDirectory() == Base + "/source";

    internal static int Run(string source, string sdkDirectory, string[] projects, bool check, string configuration,
        string framework, string[] packageInputs, string? mappings, string? manifest, string? runfiles, QualificationOptions options)
    {
        if (!OperatingSystem.IsLinux() || !File.Exists("/usr/bin/bwrap"))
        {
            throw new InvalidDataException("Qualification caching requires Linux and /usr/bin/bwrap for stable private paths");
        }
        if (runfiles is not null)
        {
            RequireRegularTree(runfiles);
        }
        var scratch = Directory.CreateTempSubdirectory("qualification-sandbox-").FullName;
        try
        {
            Directory.CreateDirectory(Path.Combine(scratch, ".local/share"));
            Directory.CreateDirectory(options.Directory);
            Directory.CreateDirectory(Path.Combine(scratch, "output"));
            var sdk = Path.GetDirectoryName(WorkspaceView.PhysicalPath(Path.Combine(Path.GetDirectoryName(Path.GetDirectoryName(sdkDirectory))!, "dotnet")))!;
            var runner = Path.GetDirectoryName(WorkspaceView.PhysicalPath(Assembly.GetExecutingAssembly().Location))!;
            var start = new ProcessStartInfo("/usr/bin/bwrap");
            void Args(params string[] values)
            {
                foreach (var value in values)
                {
                    start.ArgumentList.Add(value);
                }
            }
            Args("--die-with-parent", "--unshare-user", "--unshare-pid", "--unshare-ipc", "--unshare-uts", "--hostname", "rules-msbuild-sync",
                "--new-session", "--cap-drop", "ALL", "--clearenv", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp");
            foreach (var path in new[] { "/usr", "/bin", "/lib", "/lib64", "/etc/ld.so.cache", "/etc/os-release", "/etc/passwd", "/etc/group", "/etc/ssl/certs", "/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf" })
            {
                if (Path.Exists(path))
                {
                    Args("--ro-bind", path, path);
                }
            }
            Args("--ro-bind", sdk, Base + "/sdk", "--ro-bind", runner, Base + "/runner",
                "--ro-bind", source, Base + "/source", "--bind", scratch, Base + "/scratch",
                "--bind", Path.Combine(scratch, "output"), Base + "/output",
                "--bind", Path.GetFullPath(options.Directory), Base + "/cache", "--chdir", Base + "/source");
            if (runfiles is not null)
            {
                Args("--ro-bind", runfiles, Base + "/runfiles");
            }
            if (manifest is not null)
            {
                Args("--ro-bind", manifest, Base + "/inputs.json");
            }
            if (mappings is not null)
            {
                Args("--ro-bind", mappings, Base + "/mappings.json");
            }
            foreach (var (key, value) in new Dictionary<string, string>
            {
                ["RULES_MSBUILD_SYNC_SANDBOX"] = "1",
                ["DOTNET_ROOT"] = Base + "/sdk",
                ["HOME"] = Base + "/scratch",
                ["DOTNET_CLI_HOME"] = Base + "/scratch",
                ["PATH"] = Base + "/sdk:/usr/bin:/bin",
                ["TMPDIR"] = "/tmp",
                ["LANG"] = "C.UTF-8",
                ["TZ"] = "UTC",
                ["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1",
                ["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1",
                ["DOTNET_NOLOGO"] = "1",
                ["DOTNET_GENERATE_ASPNET_CERTIFICATE"] = "false",
                ["DOTNET_MULTILEVEL_LOOKUP"] = "0",
                ["MSBUILDDISABLENODEREUSE"] = "1"
            })
            {
                Args("--setenv", key, value);
            }
            foreach (var name in new[] { "RULES_MSBUILD_SYNC_PROFILE", "RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN", "DOTNET_PROCESSOR_COUNT" })
            {
                if (Environment.GetEnvironmentVariable(name) is { } value)
                {
                    Args("--setenv", name, value);
                }
            }
            Args("--", Base + "/sdk/dotnet", Base + "/runner/ProjectSync.dll", Base + "/source", Base + "/sdk/sdk/" + Path.GetFileName(sdkDirectory));
            Args(projects);
            Args("--package-build", "--resolve-references", "--qualification-cache", Base + "/cache", "--configuration", configuration);
            if (framework.Length != 0)
            {
                Args("--framework", framework);
            }
            if (mappings is not null)
            {
                Args("--mappings", Base + "/mappings.json");
            }
            if (manifest is not null)
            {
                Args("--inputs", Base + "/inputs.json", "--runfiles", Base + "/runfiles");
            }
            if (options.Url is not null)
            {
                Args("--qualification-cache-url", options.Url);
            }
            foreach (var input in packageInputs)
            {
                Args("--package-input", input);
            }
            using var process = Process.Start(start)!;
            process.WaitForExit();
            if (process.ExitCode == 0)
            {
                PreparedSync.Publish(check ? [Path.Combine(scratch, "output"), source, "--check"] : [Path.Combine(scratch, "output"), source]);
            }
            return process.ExitCode;
        }
        finally
        {
            Directory.Delete(scratch, true);
        }
    }

    private static void RequireRegularTree(string directory)
    {
        foreach (var path in Directory.EnumerateFileSystemEntries(directory))
        {
            if (new FileInfo(path).LinkTarget is not null)
            {
                throw new InvalidDataException("Qualification cache runfiles require materialized files and directories: " + path);
            }
            if (Directory.Exists(path))
            {
                RequireRegularTree(path);
            }
        }
    }
}
