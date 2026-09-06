using System.Diagnostics;
using System.Text;
using System.Text.RegularExpressions;

namespace ActionRunner;

internal static class Msbuild
{
    private const string Targets = "GetTargetFrameworks;Build;GetNativeManifest;GetCopyToOutputDirectoryItems;" +
        "GetTargetFrameworksWithPlatformForSingleTargetFramework;GetCopyToPublishDirectoryItems";

    public static async Task Run(ActionRequest request, Workspace workspace, string bundle, string[] packages)
    {
        string[] args = ["msbuild", $"{request.Project}/{request.Project}.csproj",
            "-t:" + (request.Project == "Shared" ? Targets : "Build"), "-p:Configuration=Release",
            "-graphBuild", "-isolateProjects", "-nodeReuse:false", "-nologo", "-verbosity:normal"];
        var start = new ProcessStartInfo(workspace.Dotnet)
        {
            WorkingDirectory = workspace.Root, UseShellExecute = false,
            RedirectStandardOutput = true, RedirectStandardError = true
        };
        foreach (var arg in args) start.ArgumentList.Add(arg);
        var env = new Dictionary<string, string>
        {
            ["DOTNET_ROOT"] = workspace.SdkRoot, ["DOTNET_CLI_HOME"] = Path.Combine(workspace.Scratch, "home"),
            ["NUGET_PACKAGES"] = Path.Combine(workspace.Root, ".nuget/packages"),
            ["DOTNET_NOLOGO"] = "1", ["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1", ["MSBUILDDISABLENODEREUSE"] = "1",
            ["TMPDIR"] = workspace.Scratch, ["TMP"] = workspace.Scratch, ["TEMP"] = workspace.Scratch,
            ["SPIKE_REPLAY_MODE"] = request.Project == "Shared" ? "capture" : "replay",
            ["SPIKE_REPLAY_WORKSPACE"] = workspace.Root, ["SPIKE_REPLAY_BUNDLE"] = bundle
        };
        foreach (var (key, value) in env) start.Environment[key] = value;
        using var process = new Process { StartInfo = start };
        var log = new StringBuilder();
        void Append(object sender, DataReceivedEventArgs e)
        {
            if (e.Data is not null) lock (log) log.AppendLine(e.Data);
        }
        process.OutputDataReceived += Append;
        process.ErrorDataReceived += Append;
        process.Start();
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();
        using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(180));
        var timedOut = false;
        try { await process.WaitForExitAsync(timeout.Token); }
        catch (OperationCanceledException)
        {
            timedOut = true;
            process.Kill(entireProcessTree: true);
            await process.WaitForExitAsync();
        }
        var text = log.ToString();
        File.WriteAllText(Path.Combine(workspace.Diagnostics, "build.log"), text);
        string[] Matches(string pattern) => Regex.Matches(text, pattern).Select(m => m.Groups[1].Value.TrimEnd('\r')).ToArray();
        var compiledProjects = Matches(@"SPIKE_COMPILE:(\w+)");
        var replayHits = Matches(@"SPIKE_REPLAY_HIT:(.*)");
        JsonFiles.Write(Path.Combine(workspace.Diagnostics, "action.json"), new
        {
            project = request.Project, workspace = workspace.Root, command = new[] { workspace.Dotnet }.Concat(args),
            packages, packageTargets = Matches(@"SPIKE_PACKAGE_TARGET:(\w+)"), returncode = process.ExitCode,
            compiledProjects, replayHits,
            sharedSources = Directory.EnumerateFiles(Path.Combine(workspace.Root, "Shared"), "*.cs")
                .Select(p => Path.GetRelativePath(workspace.Root, p)).Order(StringComparer.Ordinal).ToArray()
        });
        Console.Write(text);
        if (timedOut) throw new TimeoutException("MSBuild exceeded 180 seconds");
        if (process.ExitCode != 0) throw new InvalidOperationException($"MSBuild {request.Project} failed with {process.ExitCode}");
        if (!compiledProjects.SequenceEqual([request.Project]))
            throw new InvalidOperationException("unexpected project compilation: " + string.Join(", ", compiledProjects));
        if (request.Project == "App" && !replayHits.SequenceEqual(["Shared"]))
            throw new InvalidOperationException("App did not replay Shared");
    }
}
