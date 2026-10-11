using Microsoft.Build.Evaluation;
using Microsoft.Build.Execution;

namespace RulesMSBuild;

// SDK discovery walks to the filesystem root, including Bazel's input/output
// ancestors. Only that automatic discovery is bounded; authored reads still fail
// normal input validation when they leave the declared workspace.
internal static class AnalyzerConfigs
{
    internal static bool IsAmbient(ProjectItem item, string root, string sdkRoot)
    {
        if (item.ItemType is not ("EditorConfigFiles" or "GlobalAnalyzerConfigFiles"))
        {
            return false;
        }
        var document = item.Xml.ContainingProject.FullPath;
        if (!document.StartsWith(Path.TrimEndingDirectorySeparator(sdkRoot) + Path.DirectorySeparatorChar, StringComparison.Ordinal) ||
            Path.GetFileName(document) != "Microsoft.Managed.Core.targets")
        {
            return false;
        }
        var path = item.GetMetadataValue("FullPath");
        return path.Length != 0 && !path.StartsWith(Path.TrimEndingDirectorySeparator(root) + Path.DirectorySeparatorChar, StringComparison.Ordinal) &&
            !path.StartsWith(Path.TrimEndingDirectorySeparator(sdkRoot) + Path.DirectorySeparatorChar, StringComparison.Ordinal);
    }

    internal static void Bound(Project project, ProjectInstance instance, string root, string sdkRoot)
    {
        foreach (var kind in new[] { "EditorConfigFiles", "GlobalAnalyzerConfigFiles" })
        {
            var ambient = project.GetItems(kind).Where(item => IsAmbient(item, root, sdkRoot))
                .GroupBy(item => item.GetMetadataValue("FullPath"), StringComparer.Ordinal)
                .ToDictionary(group => group.Key, group => group.Count(), StringComparer.Ordinal);
            foreach (var item in instance.GetItems(kind).ToArray())
            {
                var path = item.GetMetadataValue("FullPath");
                if (ambient.TryGetValue(path, out var count) && count != 0)
                {
                    instance.RemoveItem(item);
                    ambient[path] = count - 1;
                }
            }
        }
    }
}
