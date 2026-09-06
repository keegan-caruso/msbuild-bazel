using System.Diagnostics;

namespace ActionRunner;

internal sealed record BuildInvocation(string Executable, string WorkingDirectory, string[] Arguments,
    IReadOnlyDictionary<string, string> Environment)
{
    private const string SharedTargets = "GetTargetFrameworks;Build;GetNativeManifest;GetCopyToOutputDirectoryItems;" +
        "GetTargetFrameworksWithPlatformForSingleTargetFramework;GetCopyToPublishDirectoryItems";

    public static BuildInvocation Create(ActionRequest request, Workspace workspace, string bundle) => new(
        workspace.Dotnet,
        workspace.Root,
        ["msbuild", $"{request.Project}/{request.Project}.csproj",
            "-t:" + (request.Project == ProjectKind.Shared ? SharedTargets : "Build"), "-p:Configuration=Release",
            "-graphBuild", "-isolateProjects", "-nodeReuse:false", "-nologo", "-verbosity:normal"],
        new Dictionary<string, string>
        {
            ["DOTNET_ROOT"] = workspace.SdkRoot,
            ["DOTNET_CLI_HOME"] = Path.Combine(workspace.Scratch, "home"),
            ["NUGET_PACKAGES"] = Path.Combine(workspace.Root, ".nuget/packages"),
            ["DOTNET_NOLOGO"] = "1",
            ["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1",
            ["MSBUILDDISABLENODEREUSE"] = "1",
            ["TMPDIR"] = workspace.Scratch,
            ["TMP"] = workspace.Scratch,
            ["TEMP"] = workspace.Scratch,
            ["SPIKE_REPLAY_MODE"] = request.Project == ProjectKind.Shared ? "capture" : "replay",
            ["SPIKE_REPLAY_WORKSPACE"] = workspace.Root,
            ["SPIKE_REPLAY_BUNDLE"] = bundle,
            ["SPIKE_REPLAY_PLUGIN"] = Path.GetFullPath(request.Plugin),
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
        return start;
    }
}
