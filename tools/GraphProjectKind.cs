using Microsoft.Build.Execution;
using Microsoft.Build.Graph;

namespace RulesMSBuild;

// Traversal and NoTargets import the .NET SDK without compiling an assembly.
// Keep evaluated properties intact; only artifact/cache classification differs.
internal static class GraphProjectKind
{
    // F# inline bodies and optimization metadata live in implementation DLLs.
    internal static HashSet<ProjectGraphNode> ImplementationReferenceNodes(ProjectGraph graph)
    {
        var result = new HashSet<ProjectGraphNode>();
        var pending = new Stack<ProjectGraphNode>(graph.ProjectNodes.Where(node =>
            Path.GetExtension(node.ProjectInstance.FullPath).Equals(".fsproj", StringComparison.OrdinalIgnoreCase)));
        while (pending.TryPop(out var current))
        {
            if (!result.Add(current))
            {
                continue;
            }
            foreach (var consumer in current.ReferencingProjects)
            {
                pending.Push(consumer);
            }
        }
        return result;
    }

    internal static bool IsTraversal(ProjectInstance project) =>
        project.GetPropertyValue("UsingMicrosoftTraversalSdk").Equals("true", StringComparison.OrdinalIgnoreCase);

    internal static bool IsNoTargets(ProjectInstance project) =>
        project.GetPropertyValue("UsingMicrosoftNoTargetsSdk").Equals("true", StringComparison.OrdinalIgnoreCase);

    internal static bool HasAssembly(ProjectInstance project) =>
        !IsTraversal(project) && !IsNoTargets(project) && project.GetPropertyValue("TargetPath").Length != 0;
}
