using Microsoft.Build.Evaluation;
using Microsoft.Build.Graph;

namespace RulesMSBuild.ProjectSync;

internal static class NuGetGraph
{
    // Traversal Restore can skip projects with failed SDK resolution and still
    // exit successfully. Require a complete evaluation before publishing locks.
    internal static string[] Projects(string root, IEnumerable<string> entries, string configuration)
    {
        var previous = Directory.GetCurrentDirectory();
        try
        {
            Directory.SetCurrentDirectory(root);
            using var collection = new ProjectCollection();
            var properties = new Dictionary<string, string> { ["Configuration"] = configuration };
            var graph = new ProjectGraph(entries.Select(entry => new ProjectGraphEntryPoint(Path.Combine(root, entry), properties)), collection,
                (path, globals, projects) => Project.FromFile(path, new Microsoft.Build.Definition.ProjectOptions
                {
                    GlobalProperties = globals,
                    ProjectCollection = projects
                }).CreateProjectInstance());
            return graph.ProjectNodes.Select(node => WorkspaceView.Safe(Path.GetRelativePath(root, node.ProjectInstance.FullPath).Replace('\\', '/')))
                .Distinct().Order(StringComparer.Ordinal).ToArray();
        }
        finally
        {
            Directory.SetCurrentDirectory(previous);
        }
    }
}
