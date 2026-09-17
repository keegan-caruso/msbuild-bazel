namespace NativeCache;

internal static class PortableEnvironment
{
    internal const string Policy = "owned-net10-release-env-v1";
    internal static Dictionary<string, string> Create(string sdk, string home, string temp, string workspace) => new()
    {
        ["PATH"] = "/usr/bin:/bin",
        ["LANG"] = "en_US.UTF-8",
        ["HOME"] = home,
        ["DOTNET_ROOT"] = sdk,
        ["DOTNET_HOST_PATH"] = Path.Combine(sdk, "dotnet"),
        ["DOTNET_CLI_HOME"] = home,
        ["NUGET_PACKAGES"] = Path.Combine(workspace, ".nuget/packages"),
        ["DOTNET_NOLOGO"] = "1",
        ["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1",
        ["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1",
        ["MSBUILDDISABLENODEREUSE"] = "1",
        ["TMPDIR"] = temp,
        ["TMP"] = temp,
        ["TEMP"] = temp
    };
}
