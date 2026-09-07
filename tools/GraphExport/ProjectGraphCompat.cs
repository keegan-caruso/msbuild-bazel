using Microsoft.Build.Evaluation;
using Microsoft.Build.Graph;

// Keep collection ownership and configured traversal roots explicit. The SDK
// reference negotiation callback selects the same inner build as ordinary MSBuild.
internal sealed class ProjectGraph
{
    private readonly Microsoft.Build.Graph.ProjectGraph inner;

    public ProjectGraph(IEnumerable<ProjectGraphEntryPoint> entryPoints, ProjectCollection collection)
    {
        ArgumentNullException.ThrowIfNull(collection);
        inner = new Microsoft.Build.Graph.ProjectGraph(entryPoints, collection, ReferenceFrameworkNegotiation.CreateProject, 1, CancellationToken.None);
    }

    public IReadOnlyCollection<ProjectGraphNode> ProjectNodes => inner.ProjectNodes;

    public IReadOnlyCollection<ProjectGraphNode> EntryPointNodes =>
        inner.EntryPointNodes.SelectMany(ExpandConfiguredRoots).Distinct().ToArray();

    private static IEnumerable<ProjectGraphNode> ExpandConfiguredRoots(ProjectGraphNode node)
    {
        if (string.Equals(Path.GetExtension(node.ProjectInstance.FullPath), ".csproj", StringComparison.OrdinalIgnoreCase))
        {
            yield return node;
            yield break;
        }

        var comparer = OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;
        var directReferencePaths = node.ProjectInstance.GetItems("ProjectReference")
            .Select(item => item.GetMetadataValue("FullPath"))
            .Where(path => !string.IsNullOrWhiteSpace(path))
            .Select(Path.GetFullPath)
            .ToHashSet(comparer);

        foreach (var reference in node.ProjectReferences.Where(reference =>
                     directReferencePaths.Contains(Path.GetFullPath(reference.ProjectInstance.FullPath))))
        {
            foreach (var root in ExpandConfiguredRoots(reference))
                yield return root;
        }
    }
}
