using Microsoft.Build.Evaluation;
using Microsoft.Build.Graph;

namespace RulesMSBuild.ProjectSync;

internal static class NuGetGraph
{
    // Traversal Restore can skip projects with failed SDK resolution and still
    // exit successfully. Require a complete evaluation before publishing locks.
    internal static string[] Projects(string root, IEnumerable<string> entries, Dictionary<string, string> defaults, Dictionary<string, Dictionary<string, string>> overrides)
    {
        var previous = Directory.GetCurrentDirectory();
        try
        {
            Directory.SetCurrentDirectory(root);
            using var collection = new ProjectCollection();
            var graph = new ProjectGraph(entries.Select(entry => new ProjectGraphEntryPoint(Path.Combine(root, entry), GraphEntryProperties.For(entry, defaults, overrides)
                .Where(pair => !pair.Key.Equals("TargetFramework", StringComparison.OrdinalIgnoreCase)).ToDictionary(pair => pair.Key, pair => pair.Value, StringComparer.OrdinalIgnoreCase))), collection,
                // Use MSBuild's ProjectInstance evaluator. Project.FromFile also
                // collects conditioned properties inside false item groups; an
                // outer build can then evaluate functions needing an inner TFM.
                null);
            return graph.ProjectNodes.Select(node => WorkspaceView.Safe(Path.GetRelativePath(root, node.ProjectInstance.FullPath).Replace('\\', '/')))
                .Distinct().Order(StringComparer.Ordinal).ToArray();
        }
        finally
        {
            Directory.SetCurrentDirectory(previous);
        }
    }
}
