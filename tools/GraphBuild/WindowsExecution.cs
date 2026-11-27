namespace RulesMSBuild.GraphBuild;

[System.Runtime.Versioning.SupportedOSPlatform("windows")]
internal static class WindowsExecution
{
    internal static Dictionary<string, string> Prepare(WindowsSandboxLease lease)
    {
        foreach (var directory in new[] { "scratch", "scratch/appdata", "scratch/localappdata", "scratch/programfiles" })
        {
            Directory.CreateDirectory(Path.Combine(lease.Action, directory));
        }
        WindowsStorage.Permissions(lease.Action, lease.Profile.Identifier);
        WindowsStorage.IntegrityTree(lease.Action, false);
        foreach (var directory in new[] { "output", "scratch" })
        {
            var writable = Path.Combine(lease.Action, directory);
            WindowsStorage.Permissions(writable, lease.Profile.Identifier, true);
            WindowsStorage.IntegrityTree(writable, true);
        }
        lease.AllocateDrive();
        var root = lease.Root;
        var scratch = root + "scratch";
        var environment = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            ["SystemRoot"] = Environment.GetEnvironmentVariable("SystemRoot") ?? throw new IOException("SystemRoot is required"),
            ["WINDIR"] = Environment.GetEnvironmentVariable("WINDIR") ?? throw new IOException("WINDIR is required"),
            ["ComSpec"] = Path.Combine(Environment.SystemDirectory, "cmd.exe"),
            ["PATH"] = root + "sdk;" + Environment.SystemDirectory,
            ["DOTNET_ROOT"] = root + "sdk",
            ["HOME"] = scratch,
            ["DOTNET_CLI_HOME"] = scratch,
            ["USERPROFILE"] = scratch,
            ["APPDATA"] = scratch + "\\appdata",
            ["LOCALAPPDATA"] = scratch + "\\localappdata",
            ["PROGRAMFILES"] = scratch + "\\programfiles",
            ["NUGET_PACKAGES"] = scratch + "\\packages",
            ["TEMP"] = scratch,
            ["TMP"] = scratch,
            ["SystemTemp"] = scratch,
            ["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1",
            ["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1",
            ["DOTNET_NOLOGO"] = "1",
            ["DOTNET_ADD_GLOBAL_TOOLS_TO_PATH"] = "false",
            ["DOTNET_GENERATE_ASPNET_CERTIFICATE"] = "false",
            ["DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE"] = "true",
            ["DOTNET_CLI_USE_MSBUILD_SERVER"] = "false",
            ["MSBUILDUSESERVER"] = "0",
            ["MSBUILDDISABLENODEREUSE"] = "1",
            ["DOTNET_EnableDiagnostics"] = "0"
        };
        return environment;
    }

    internal static async Task<int> Run(WindowsSandboxLease lease, IReadOnlyList<string> arguments, string workingDirectory,
        Dictionary<string, string> environment)
    {
        using var stop = new CancellationTokenSource(WorkerProcess.RequestTimeout);
        ConsoleCancelEventHandler cancel = (_, eventArgs) => { eventArgs.Cancel = true; stop.Cancel(); };
        Console.CancelKeyPress += cancel;
        try
        {
            return await WindowsProcess.Run(lease.Profile, lease.JobName, lease.Root + "sdk\\dotnet.exe", arguments,
                workingDirectory, environment, lease.Started, stop.Token);
        }
        finally
        {
            Console.CancelKeyPress -= cancel;
        }
    }
}
