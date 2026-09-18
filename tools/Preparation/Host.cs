using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

internal static class Host
{
    public static string Relative(string value)
    {
        if (!value.StartsWith("workspace/", StringComparison.Ordinal)) throw new InvalidDataException("expected workspace path: " + value);
        return Safe(value[10..]);
    }
    public static string Safe(string value)
    {
        if (string.IsNullOrEmpty(value) || Path.IsPathRooted(value) || value.Split('/').Any(p => p is "" or "." or "..") || value.IndexOfAny([':', '\\', '\n', '\r']) >= 0)
            throw new InvalidDataException("unsafe workspace path: " + value);
        return value;
    }
    public static bool Within(string path, string root) => path == root || path.StartsWith(root.TrimEnd('/') + "/", StringComparison.Ordinal);
    public static string Real(string path)
    {
        path = Path.GetFullPath(path);
        var current = Path.GetPathRoot(path)!;
        foreach (var component in path[current.Length..].Split('/', StringSplitOptions.RemoveEmptyEntries))
        {
            current = Path.Combine(current, component);
            FileSystemInfo info = Directory.Exists(current) ? new DirectoryInfo(current) : new FileInfo(current);
            if (info.LinkTarget is not null) current = info.ResolveLinkTarget(true)?.FullName ?? throw new IOException("Broken link: " + current);
        }
        return current;
    }
    public static void Copy(string source, string target)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        File.Copy(source, target, true);
    }
    public static string Run(string executable, IEnumerable<string> args, string cwd, Dictionary<string, string>? environment = null)
    {
        var start = new ProcessStartInfo(executable) { WorkingDirectory = cwd, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var arg in args) start.ArgumentList.Add(arg);
        if (environment is not null) foreach (var pair in environment) start.Environment[pair.Key] = pair.Value;
        using var process = Process.Start(start) ?? throw new IOException("Cannot start " + executable);
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        process.WaitForExit();
        Task.WaitAll(stdout, stderr);
        if (process.ExitCode != 0) throw new IOException(executable + " failed: " + stdout.Result + stderr.Result);
        return stdout.Result;
    }
    public static Dictionary<string, string> SdkEnvironment(string sdk, string version)
    {
        var engine = Path.Combine(sdk, "sdk", version);
        return new()
        {
            ["DOTNET_ROOT"] = sdk,
            ["DOTNET_HOST_PATH"] = Path.Combine(sdk, "dotnet"),
            ["MSBUILD_EXE_PATH"] = Path.Combine(engine, "MSBuild.dll"),
            ["MSBuildSDKsPath"] = Path.Combine(engine, "Sdks"),
            ["DOTNET_MSBUILD_SDK_RESOLVER_CLI_DIR"] = sdk,
            ["DOTNET_MSBUILD_SDK_RESOLVER_SDKS_DIR"] = Path.Combine(engine, "Sdks"),
            ["DOTNET_MSBUILD_SDK_RESOLVER_SDKS_VER"] = version
        };
    }
    public static IDisposable Lock(string path)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        return new Lease(path);
    }
    private sealed class Lease : IDisposable
    {
        private readonly FileStream stream;
        public Lease(string path)
        {
            stream = new FileStream(path, FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.ReadWrite);
            if (Flock(stream.SafeFileHandle.DangerousGetHandle().ToInt32(), 2) != 0)
            {
                stream.Dispose();
                throw new IOException("Cannot acquire preparation lock");
            }
        }
        public void Dispose() => stream.Dispose();
        [DllImport("libc", EntryPoint = "flock", SetLastError = true)]
        private static extern int Flock(int fd, int operation);
    }
}
