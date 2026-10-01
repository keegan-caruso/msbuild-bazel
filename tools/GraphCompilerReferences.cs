using Microsoft.Build.Graph;

namespace RulesMSBuild;

// A reviewed SDK can select a separately authored contract instead of TargetRefPath.
// The declaration identifies an existing producer; it does not change compilation.
internal static class GraphCompilerReferences
{
    internal static void Validate(ProjectGraphNode node, string? path, Func<ProjectGraphNode, IEnumerable<string>> products)
    {
        if (path is null)
        {
            return;
        }
        if (node.ProjectInstance.GetPropertyValue("TargetPath").Length == 0 || !Path.GetExtension(path).Equals(".dll", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("Compiler reference requires a configured managed DLL producer: " + path);
        }
        var seen = new HashSet<ProjectGraphNode>();
        var pending = new Stack<ProjectGraphNode>();
        pending.Push(node);
        while (pending.TryPop(out var current))
        {
            if (!seen.Add(current))
            {
                continue;
            }
            if (products(current).Contains(path, StringComparer.Ordinal))
            {
                return;
            }
            foreach (var dependency in current.ProjectReferences)
            {
                pending.Push(dependency);
            }
        }
        throw new InvalidDataException("Compiler reference must name a declared project output in the producer dependency closure: " + path);
    }
}
