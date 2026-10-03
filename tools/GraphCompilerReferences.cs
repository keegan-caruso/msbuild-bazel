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
        if (!GraphProjectKind.HasAssembly(node.ProjectInstance) || !Path.GetExtension(path).Equals(".dll", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("Compiler reference requires a configured managed DLL producer: " + path);
        }
        if (!OwnsOutput(node, path, products))
        {
            throw new InvalidDataException("Compiler reference must name a declared project output in the producer dependency closure: " + path);
        }
    }

    internal static void ValidateConsumer(ProjectGraphNode node, string producer, string path, Func<ProjectGraphNode, IEnumerable<string>> products)
    {
        if (!GraphProjectKind.HasAssembly(node.ProjectInstance) || !Path.GetExtension(path).Equals(".dll", StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("Consumer compiler references require a configured managed DLL consumer: " + path);
        }
        var seen = new HashSet<ProjectGraphNode>();
        var pending = new Stack<ProjectGraphNode>(node.ProjectReferences);
        while (pending.TryPop(out var current))
        {
            if (!seen.Add(current))
            {
                continue;
            }
            if (current.ProjectInstance.FullPath == producer && GraphProjectKind.HasAssembly(current.ProjectInstance) && OwnsOutput(current, path, products))
            {
                return;
            }
            foreach (var dependency in current.ProjectReferences)
            {
                pending.Push(dependency);
            }
        }
        throw new InvalidDataException("Consumer compiler reference must name a declared output in the selected producer dependency closure: " + producer + " -> " + path);
    }

    private static bool OwnsOutput(ProjectGraphNode node, string path, Func<ProjectGraphNode, IEnumerable<string>> products)
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
            if (products(current).Contains(path, StringComparer.Ordinal))
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
}
