using System.Text;
using Microsoft.Build.Evaluation;
using Microsoft.Build.Execution;
using Microsoft.Build.Framework;
using Microsoft.Build.Logging;

internal static class ReferenceFrameworkNegotiation
{
    private static readonly object ResolutionLock = new();

    public static ProjectInstance CreateProject(string path, Dictionary<string, string> globals, ProjectCollection collection)
    {
        var instance = new ProjectInstance(path, globals, null, collection);
        if (!path.EndsWith(".csproj", StringComparison.OrdinalIgnoreCase) ||
            string.IsNullOrEmpty(instance.GetPropertyValue("TargetFramework")))
            return instance;

        instance.SetProperty("InnerBuildProperty", "");
        instance.SetProperty("InnerBuildPropertyValues", "");
        if (instance.GetItems("ProjectReference").Count == 0) return instance;

        // Let the pinned SDK negotiate references as ordinary MSBuild does. The
        // returned metadata shapes the graph only; source projects are unchanged.
        BuildResult result;
        var log = new StringBuilder();
        lock (ResolutionLock)
        {
            using var manager = new BuildManager();
            result = manager.Build(new BuildParameters
            {
                EnableNodeReuse = false,
                MaxNodeCount = 1,
                Loggers = [new ConsoleLogger(LoggerVerbosity.Minimal, text => log.Append(text), null, null)],
            }, new BuildRequestData(instance.DeepCopy(), ["PrepareProjectReferences"], null,
                BuildRequestDataFlags.ProvideProjectStateAfterBuild));
        }
        if (result.OverallResult != BuildResultCode.Success || result.ProjectStateAfterBuild is null)
            throw new ExportException("reference-framework-discovery-failed", "SDK reference negotiation failed: " + path + "\n" + log);
        var resolved = result.ProjectStateAfterBuild.GetItems("_MSBuildProjectReferenceExistent");
        foreach (var reference in instance.GetItems("ProjectReference"))
        {
            var fullPath = Path.GetFullPath(reference.GetMetadataValue("FullPath"));
            var matches = resolved.Where(item => Path.GetFullPath(item.GetMetadataValue("FullPath")) == fullPath).ToArray();
            if (matches.Length != 1)
                throw new ExportException("unsupported-configured-reference", "SDK reference negotiation is missing or ambiguous: " + fullPath);
            var selected = matches[0].GetMetadataValue("SetTargetFramework");
            if (!string.IsNullOrEmpty(selected)) reference.SetMetadata("SetTargetFramework", selected);
        }
        return instance;
    }
}
