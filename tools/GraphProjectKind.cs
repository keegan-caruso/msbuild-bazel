using Microsoft.Build.Execution;

namespace RulesMSBuild;

// Traversal and NoTargets import the .NET SDK without compiling an assembly.
// Keep evaluated properties intact; only artifact/cache classification differs.
internal static class GraphProjectKind
{
    internal static bool IsTraversal(ProjectInstance project) =>
        project.GetPropertyValue("UsingMicrosoftTraversalSdk").Equals("true", StringComparison.OrdinalIgnoreCase);

    internal static bool IsNoTargets(ProjectInstance project) =>
        project.GetPropertyValue("UsingMicrosoftNoTargetsSdk").Equals("true", StringComparison.OrdinalIgnoreCase);

    internal static bool HasAssembly(ProjectInstance project) =>
        !IsTraversal(project) && !IsNoTargets(project) && project.GetPropertyValue("TargetPath").Length != 0;
}
