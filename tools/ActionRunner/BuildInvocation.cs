using System.Diagnostics;

namespace ActionRunner;

internal sealed record BuildInvocation(string Executable, string WorkingDirectory, string[] Arguments,
    IReadOnlyDictionary<string, string> Environment)
{
    private const string SharedTargets = "GetTargetFrameworks;Build;GetNativeManifest;GetCopyToOutputDirectoryItems;" +
        "GetTargetFrameworksWithPlatformForSingleTargetFramework;GetCopyToPublishDirectoryItems";

    public static BuildInvocation Create(ActionRequest request, Workspace workspace, string bundle) => Create(
        request, workspace, bundle, LoaderRuntime.Stage(request, workspace));

    private static BuildInvocation Create(ActionRequest request, Workspace workspace, string bundle, string dotnet) => new(
        dotnet,
        workspace.Root,
        [.. (request.LoaderJit is null ? new[] { "msbuild" } :
            new[] { "exec", Path.Combine(workspace.SdkRoot, "sdk", "10.0.400", "MSBuild.dll") }),
            $"{request.Project}/{request.Project}.csproj",
            "-t:" + (request.Project == ProjectKind.Shared ? SharedTargets : "Build"), "-p:Configuration=Release",
            "-graphBuild", "-isolateProjects", "-nodeReuse:false", "-nologo", "-verbosity:normal"],
        new Dictionary<string, string>
        {
            ["RULES_MSBUILD_LOADER_TRACE_PATH"] = Path.Combine(workspace.Diagnostics, "loader.log"),
            ["DOTNET_ROOT"] = Path.GetDirectoryName(dotnet)!,
            ["DOTNET_CLI_HOME"] = Path.Combine(workspace.Scratch, "home"),
            ["NUGET_PACKAGES"] = Path.Combine(workspace.Root, ".nuget/packages"),
            ["DOTNET_NOLOGO"] = "1",
            ["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1",
            ["MSBUILDDISABLENODEREUSE"] = "1",
            ["TMPDIR"] = workspace.Scratch,
            ["TMP"] = workspace.Scratch,
            ["TEMP"] = workspace.Scratch,
            ["RULES_MSBUILD_REPLAY_MODE"] = request.Project == ProjectKind.Shared ? "capture" : "replay",
            ["RULES_MSBUILD_REPLAY_WORKSPACE"] = workspace.Root,
            ["RULES_MSBUILD_REPLAY_BUNDLE"] = bundle,
            ["RULES_MSBUILD_REPLAY_PLUGIN"] = Path.GetFullPath(request.Plugin),
            // Environment properties remain local to evaluation; global action paths would break replay identity.
            ["DirectoryBuildPropsPath"] = Path.GetFullPath(request.BuildProps),
            ["DirectoryBuildTargetsPath"] = Path.GetFullPath(request.BuildTargets)
        });

    public ProcessStartInfo CreateStartInfo()
    {
        var start = new ProcessStartInfo(Executable, Arguments)
        {
            WorkingDirectory = WorkingDirectory,
            UseShellExecute = false,
            RedirectStandardOutput = true,
            RedirectStandardError = true
        };
        foreach (var (key, value) in Environment)
            start.Environment[key] = value;
        // Set loader flags at the MSBuild child boundary. macOS sandbox
        // launchers can strip DYLD_* variables before the runner starts.
        if (System.Environment.GetEnvironmentVariable("RULES_MSBUILD_TRACE_RUNTIME") == "1")
        {
            start.Environment["DYLD_PRINT_LIBRARIES"] = "1";
            start.Environment["LD_DEBUG"] = "libs";
            // Compiler tasks interpret stderr as errors; keep loader output
            // in declared diagnostics instead of changing compilation behavior.
            start.Environment["DYLD_PRINT_TO_FILE"] = Environment["RULES_MSBUILD_LOADER_TRACE_PATH"];
            start.Environment["LD_DEBUG_OUTPUT"] = Environment["RULES_MSBUILD_LOADER_TRACE_PATH"];
        }
        return start;
    }
}
