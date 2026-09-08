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

        var assets = instance.GetPropertyValue("ProjectAssetsFile");
        if (!string.IsNullOrWhiteSpace(assets))
        {
            assets = Path.GetFullPath(assets, Path.GetDirectoryName(path)!);
            if (File.Exists(assets)) PackageRestoreValidation.ValidateSuccessfulRestore(instance, assets);
        }

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
            var negotiated = matches[0];
            var selected = negotiated.GetMetadataValue("SetTargetFramework");
            if (!string.IsNullOrEmpty(selected)) reference.SetMetadata("SetTargetFramework", selected);
            // Ordinary MSBuild consumes UndefineProperties on task items. The
            // static graph consumes GlobalPropertiesToRemove on ProjectReference.
            // In particular a single-target child must not inherit the parent's
            // explicit TargetFramework; let the child's declaration evaluate it.
            var removed = new[] { reference.GetMetadataValue("GlobalPropertiesToRemove"),
                negotiated.GetMetadataValue("GlobalPropertiesToRemove"), negotiated.GetMetadataValue("UndefineProperties") }
                .SelectMany(value => value.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
                .Distinct(StringComparer.OrdinalIgnoreCase);
            reference.SetMetadata("GlobalPropertiesToRemove", string.Join(';', removed));
        }
        return instance;
    }
}
