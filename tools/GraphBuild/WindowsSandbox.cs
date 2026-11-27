namespace RulesMSBuild.GraphBuild;

internal static class WindowsSandbox
{
    internal static async Task<int> Run(string[] args, GraphRunOptions options)
    {
        if (!WindowsPlatform.IsNative)
        {
            throw new PlatformNotSupportedException("Windows filesystem isolation requires matching native Windows x64 or ARM64");
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
        var environment = WindowsExecution.Prepare(lease);
        var root = lease.Root;
        environment["RULES_MSBUILD_GRAPH_COPY_MODE"] = "copy";
        environment["RULES_MSBUILD_GRAPH_SINGLE_NODE"] = "1";
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
        var result = await WindowsExecution.Run(lease, arguments, root + "output\\workspace", environment);
        if (result == 0)
        {
            // The inner job is empty before the privileged parent reads outputs.
            // Reject all reparse points rather than following task-created links.
            WindowsStorage.Copy(Path.Combine(lease.Action, "output"), output, true);
        }
        return result;
    }
}
