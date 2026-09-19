using System.Text.Json;
using Microsoft.Build.Evaluation;
using Microsoft.Build.Execution;
using Microsoft.Build.Framework;
using Microsoft.Build.Logging;

internal static class EntryBuild
{
    internal const string Targets = "Build;GetCopyToOutputDirectoryItems;GetTargetFrameworksWithPlatformForSingleTargetFramework;GetNativeManifest;GetTargetFrameworks";
    internal static int Run(string path)
    {
        var session = JsonSerializer.Deserialize<Session>(File.ReadAllText(path), new JsonSerializerOptions { PropertyNameCaseInsensitive = true })!;
        var properties = new Dictionary<string, string>
        {
            ["Configuration"] = "Release",
            ["TargetFramework"] = session.Projects[session.Entry].TargetFramework,
            ["PathMap"] = session.Workspace + "=/_/workspace",
            ["DirectoryBuildTargetsPath"] = session.TargetsPath!
        };
        using var collection = new ProjectCollection();
        var project = new ProjectInstance(Path.Combine(session.Workspace, session.Entry), properties, null, collection);
        // Orchard's application target asks each reference for its module name.
        // Capture it only when authored by that producer; SDK-less dependency
        // replay must preserve both target presence and the actual returned items.
        var targets = Targets.Split(';').Concat(new[] { "GetModuleProjectName", "GetStaticWebAssetsProjectConfiguration", "GetCurrentProjectBuildStaticWebAssetItems" }.Where(project.Targets.ContainsKey)).ToArray();
        using var manager = new BuildManager();
        var result = manager.Build(new BuildParameters(collection)
        {
            EnableNodeReuse = false,
            MaxNodeCount = 1,
            Loggers = [new ConsoleLogger(LoggerVerbosity.Normal)]
        }, new BuildRequestData(project, targets));
        return result.OverallResult == BuildResultCode.Success ? 0 : 1;
    }
}
