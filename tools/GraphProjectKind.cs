using Microsoft.Build.Execution;

namespace RulesMSBuild;

// Traversal imports the .NET SDK and inherits TargetPath without compiling it.
// Keep its evaluated properties intact; only artifact/cache classification differs.
internal static class GraphProjectKind
{
    internal static bool IsTraversal(ProjectInstance project) =>
        project.GetPropertyValue("UsingMicrosoftTraversalSdk").Equals("true", StringComparison.OrdinalIgnoreCase);

    internal static bool HasAssembly(ProjectInstance project) =>
        !IsTraversal(project) && project.GetPropertyValue("TargetPath").Length != 0;
}
