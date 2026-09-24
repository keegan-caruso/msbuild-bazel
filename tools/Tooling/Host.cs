using System.Diagnostics;

namespace RulesMSBuild.Tooling;

internal static class Host
{
    public static string Real(string path)
    {
        path = Path.GetFullPath(path);
        var current = Path.GetPathRoot(path)!;
        foreach (var component in path[current.Length..].Split('/', StringSplitOptions.RemoveEmptyEntries))
        {
            current = Path.Combine(current, component);
            FileSystemInfo info = Directory.Exists(current) ? new DirectoryInfo(current) : new FileInfo(current);
            if (info.LinkTarget is not null)
            {
                current = info.ResolveLinkTarget(true)?.FullName ?? throw new IOException("Broken link: " + current);
            }
        }
        return current;
    }
    public static string Run(string executable, IEnumerable<string> args, string cwd, Dictionary<string, string>? environment = null)
    {
        var start = new ProcessStartInfo(executable) { WorkingDirectory = cwd, RedirectStandardOutput = true, RedirectStandardError = true };
        foreach (var arg in args)
        {
            start.ArgumentList.Add(arg);
        }

        if (environment is not null)
        {
            foreach (var pair in environment)
            {
                start.Environment[pair.Key] = pair.Value;
            }
        }

        using var process = Process.Start(start) ?? throw new IOException("Cannot start " + executable);
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        process.WaitForExit();
        Task.WaitAll(stdout, stderr);
        if (process.ExitCode != 0)
        {
            throw new IOException(executable + " failed: " + stdout.Result + stderr.Result);
        }

        return stdout.Result;
    }
}
