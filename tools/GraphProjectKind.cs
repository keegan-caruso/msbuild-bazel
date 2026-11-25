using Microsoft.Build.Execution;
using Microsoft.Build.Graph;

namespace RulesMSBuild;

// Traversal and NoTargets import the .NET SDK without compiling an assembly.
// Keep evaluated properties intact; only artifact/cache classification differs.
internal static class GraphProjectKind
{
    // F# inline bodies and optimization metadata live in implementation DLLs.
    internal static bool RequiresImplementationReferences(ProjectGraphNode node)
    {
        var seen = new HashSet<ProjectGraphNode>();
        var pending = new Stack<ProjectGraphNode>();
        pending.Push(node);
        while (pending.TryPop(out var current))
        {
            if (!seen.Add(current))
            {
                continue;
            }
            if (Path.GetExtension(current.ProjectInstance.FullPath).Equals(".fsproj", StringComparison.OrdinalIgnoreCase))
            {
                return true;
            }
            foreach (var dependency in current.ProjectReferences)
            {
                pending.Push(dependency);
            }
        }
        return false;
    }

    internal static bool IsTraversal(ProjectInstance project) =>
        project.GetPropertyValue("UsingMicrosoftTraversalSdk").Equals("true", StringComparison.OrdinalIgnoreCase);

    internal static bool IsNoTargets(ProjectInstance project) =>
        project.GetPropertyValue("UsingMicrosoftNoTargetsSdk").Equals("true", StringComparison.OrdinalIgnoreCase);

    internal static bool HasAssembly(ProjectInstance project) =>
        !IsTraversal(project) && !IsNoTargets(project) && project.GetPropertyValue("TargetPath").Length != 0;
}
