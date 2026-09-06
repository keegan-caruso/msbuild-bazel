using Microsoft.Build.Evaluation;
using Microsoft.Build.Graph;

// Microsoft.Build 17.14 exposes the multi-entry constructor without a
// ProjectCollection overload. Keep collection ownership explicit at the call
// site while adapting to that supported API surface.
internal sealed class ProjectGraph
{
    private readonly Microsoft.Build.Graph.ProjectGraph inner;

    public ProjectGraph(IEnumerable<ProjectGraphEntryPoint> entryPoints, ProjectCollection collection)
    {
        ArgumentNullException.ThrowIfNull(collection);
        inner = new Microsoft.Build.Graph.ProjectGraph(entryPoints);
    }

    public IReadOnlyCollection<ProjectGraphNode> ProjectNodes => inner.ProjectNodes;

    public IReadOnlyCollection<ProjectGraphNode> EntryPointNodes => inner.EntryPointNodes;
}
