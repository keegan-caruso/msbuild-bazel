namespace RulesMSBuild.GraphBuild;

internal static class WindowsSandbox
{
    internal static async Task<int> Run(string[] args, GraphRunOptions options)
    {
        if (!OperatingSystem.IsWindows())
        {
            throw new PlatformNotSupportedException("Windows filesystem isolation requires native Windows");
        }
        if (System.Runtime.InteropServices.RuntimeInformation.OSArchitecture != System.Runtime.InteropServices.Architecture.X64 ||
            System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture != System.Runtime.InteropServices.Architecture.X64)
        {
            throw new PlatformNotSupportedException("Windows filesystem isolation currently requires native x64");
        }
        if (args.Length != 8 || args[5] is not ("action" or "prepare"))
        {
            throw new ArgumentException("Windows sandbox requires SDK RUNNER OUTPUT CONTRACT TARGET MODE PREPARED PROFILE");
        }
        if (options.RemoteUrl is not null || options.BearerToken is not null || options.LocalState is not null || options.ReadOnlyPackages)
        {
            throw new InvalidDataException("Windows filesystem isolation does not yet support remote cache, retained state or read-only prepared packages");
        }
        return await RunWindows(args, options);
    }

    [System.Runtime.Versioning.SupportedOSPlatform("windows")]
    private static async Task<int> RunWindows(string[] args, GraphRunOptions options)
    {
        var sdk = Path.GetFullPath(args[0]);
        var runner = Path.GetFullPath(args[1]);
        var output = Path.GetFullPath(args[2]);
        var contract = Path.GetFullPath(args[3]);
        var target = args[4];
        var mode = args[5];
        var prepared = args[6];
        var profile = args[7] == "1";
        if (!File.Exists(Path.Combine(sdk, "dotnet.exe")) || !File.Exists(Path.Combine(runner, "GraphBuild.dll")) ||
            !Directory.Exists(Path.Combine(output, "workspace")))
        {
            throw new InvalidDataException("Missing declared Windows graph SDK, runner or staged workspace");
        }
        using var lease = new WindowsSandboxLease();
        WindowsStorage.Integrity(lease.Action, false);
        WindowsStorage.Copy(sdk, Path.Combine(lease.Action, "sdk"));
        WindowsStorage.Copy(runner, Path.Combine(lease.Action, "runner"));
        WindowsStorage.Copy(output, Path.Combine(lease.Action, "output"));
        File.Copy(contract, Path.Combine(lease.Action, "contract.json"));
        if (prepared != "-")
        {
            WindowsStorage.Copy(Path.GetFullPath(prepared), Path.Combine(lease.Action, "prepared"));
        }
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
            ["DOTNET_EnableDiagnostics"] = "0",
            ["RULES_MSBUILD_GRAPH_COPY_MODE"] = "copy"
        };
        if (profile || options.Profile)
        {
            environment["RULES_MSBUILD_GRAPH_PROFILE"] = "1";
        }
        if (options.EvaluationProfile)
        {
            environment["RULES_MSBUILD_GRAPH_EVALUATION_PROFILE"] = "1";
        }
        if (options.ReuseBuildCache)
        {
            environment["RULES_MSBUILD_GRAPH_REUSE_BUILD_CACHE"] = "1";
        }
        if (prepared != "-")
        {
            environment["RULES_MSBUILD_GRAPH_PREPARED_RESTORE"] = root + "prepared\\prepared";
        }
        var arguments = new List<string>
        {
            "exec", root + "runner\\GraphBuild.dll", mode, root + "output\\workspace", root + "contract.json", root + "output\\report.json",
            root + (mode == "prepare" ? "output\\prepared" : "scratch\\cache")
        };
        if (mode != "prepare")
        {
            arguments.Add(target);
        }
        using var stop = new CancellationTokenSource(WorkerProcess.RequestTimeout);
        ConsoleCancelEventHandler cancel = (_, eventArgs) => { eventArgs.Cancel = true; stop.Cancel(); };
        Console.CancelKeyPress += cancel;
        int result;
        try
        {
            result = await WindowsProcess.Run(lease.Profile, lease.JobName, root + "sdk\\dotnet.exe", arguments,
                root + "output\\workspace", environment, lease.Started, stop.Token);
        }
        finally
        {
            Console.CancelKeyPress -= cancel;
        }
        if (result == 0)
        {
            // The inner job is empty before the privileged parent reads outputs.
            // Reject all reparse points rather than following task-created links.
            WindowsStorage.Copy(Path.Combine(lease.Action, "output"), output, true);
        }
        return result;
    }
}
