using System.Diagnostics;
using System.Text.Json;

internal static class Sandbox
{
    public static ProcessStartInfo Start(string workspace, string state, IEnumerable<string> runtime, string sdk)
    {
        var roots = runtime.Append(workspace).Select(Path.GetFullPath).Distinct(StringComparer.Ordinal).ToArray();
        ProcessStartInfo start;
        if (OperatingSystem.IsMacOS())
        {
            var profile = "(version 1)\n(deny default)\n(allow process-exec process-fork signal sysctl-read mach-lookup)\n" +
                "(allow file-read* file-test-existence (literal \"/\"))\n" +
                "(allow file-read* file-test-existence file-map-executable (subpath \"/System/Library\") (subpath \"/usr/lib\") (subpath \"/usr/share/icu\") (subpath \"/System/Volumes/Preboot/Cryptexes/OS\") (literal \"/bin/sh\") (literal \"/bin/bash\") (literal \"/private/var/select/sh\") (literal \"/dev/null\") (literal \"/dev/urandom\") (literal \"/dev/random\"))\n";
            foreach (var root in roots.Append(state))
            {
                profile += "(allow file-read* file-test-existence file-map-executable (subpath " + JsonSerializer.Serialize(root) + "))\n";
                for (var path = Path.GetDirectoryName(root); path is not null; path = Path.GetDirectoryName(path)) profile += "(allow file-read-metadata file-test-existence (literal " + JsonSerializer.Serialize(path) + "))\n";
            }
            foreach (var root in new[] { "/private/var/select/sh", "/bin/bash", "/System/Library", "/usr/lib", "/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld", "/System/Cryptexes/OS/System/Library/dyld" })
                for (var path = Path.GetDirectoryName(root); path is not null; path = Path.GetDirectoryName(path)) profile += "(allow file-read-metadata file-test-existence (literal " + JsonSerializer.Serialize(path) + "))\n";
            profile += "(allow file-write* (literal \"/dev/null\") (subpath " + JsonSerializer.Serialize(state) + "))\n";
            var pathToProfile = Path.Combine(state, "sandbox.sb"); File.WriteAllText(pathToProfile, profile);
            start = new ProcessStartInfo("/usr/bin/sandbox-exec"); start.ArgumentList.Add("-f"); start.ArgumentList.Add(pathToProfile);
        }
        else if (OperatingSystem.IsLinux())
        {
            start = new ProcessStartInfo("/usr/bin/bwrap");
            void Add(params string[] values) { foreach (var value in values) start.ArgumentList.Add(value); }
            Add("--die-with-parent", "--unshare-all", "--new-session", "--cap-drop", "ALL", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp");
            foreach (var root in roots.Concat(new[] { "/usr/lib" }).Distinct(StringComparer.Ordinal)) Add("--ro-bind", root, root);
            foreach (var file in new[] { "/etc/os-release", "/etc/ld.so.cache", "/etc/passwd", "/etc/group" }) Add("--ro-bind", file, file);
            Add("--symlink", "usr/lib", "/lib", "--bind", state, state, "--chdir", workspace, "--");
        }
        else throw new PlatformNotSupportedException("Explicit MSBuild requires a qualified Linux/macOS sandbox");
        SetEnvironment(start, workspace, state, sdk);
        return start;
    }
    internal static void SetEnvironment(ProcessStartInfo start, string workspace, string state, string sdk)
    {
        var migrations = Path.Combine(state, "data", "NuGet", "Migrations");
        Directory.CreateDirectory(migrations); File.WriteAllText(Path.Combine(migrations, "1"), "");
        start.WorkingDirectory = workspace; start.Environment.Clear();
        foreach (var (key, value) in new Dictionary<string, string>
        {
            ["DOTNET_ROOT"] = sdk,
            ["DOTNET_HOST_PATH"] = Path.Combine(sdk, "dotnet"),
            ["PATH"] = OperatingSystem.IsMacOS() ? sdk + ":/bin" : sdk,
            ["XDG_DATA_HOME"] = Path.Combine(state, "data"),
            ["NUGET_SCRATCH"] = Path.Combine(state, "nuget-scratch"),
            ["NUGET_HTTP_CACHE_PATH"] = Path.Combine(state, "http"),
            ["HOME"] = state,
            ["DOTNET_CLI_HOME"] = state,
            ["TMPDIR"] = state,
            ["TMP"] = state,
            ["TEMP"] = state,
            ["NUGET_PACKAGES"] = Path.Combine(state, "packages"),
            ["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1",
            ["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1",
            ["DOTNET_MULTILEVEL_LOOKUP"] = "0",
            ["DOTNET_EnableDiagnostics"] = "0",
            ["MSBuildEnableWorkloadResolver"] = "false",
            ["MSBUILDDISABLENODEREUSE"] = "1",
            ["LANG"] = "en_US.UTF-8",
            ["TZ"] = "UTC",
        }) start.Environment[key] = value;
    }
}
