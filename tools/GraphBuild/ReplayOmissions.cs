using Microsoft.Build.Graph;

namespace RulesMSBuild.GraphBuild;

// Opt-in, reviewed disposable files. Complete snapshots still retain their bytes;
// no consumer, task or export may rely on an omitted file in the action workspace.
internal sealed class ReplayOmissions
{
    private readonly GraphInputs inputs;
    private readonly Dictionary<ProjectGraphNode, HashSet<string>> omitted = [];

    internal ReplayOmissions(GraphInputs inputs)
    {
        this.inputs = inputs;
        foreach (var node in inputs.Graph.ProjectNodes)
        {
            omitted.Add(node, (inputs.For(node).ReplayOmissions ?? []).Select(inputs.Files.Resolve).ToHashSet(StringComparer.Ordinal));
        }
        if (omitted.Values.All(paths => paths.Count == 0))
        {
            return;
        }
        var required = inputs.Graph.ProjectNodes.SelectMany(node =>
            (inputs.For(node).OutputFiles ?? []).Concat((inputs.For(node).DependencyCopies ?? []).Values)
            .Concat((inputs.For(node).DependencyCopies ?? []).Keys)
            .Concat(inputs.For(node).CompilerReference is { } reference ? new[] { reference } : [])
            .Concat((inputs.For(node).CompilerReferences ?? []).Values))
            .Select(inputs.Files.Resolve).ToHashSet(StringComparer.Ordinal);
        foreach (var node in inputs.Graph.ProjectNodes)
        {
            var project = node.ProjectInstance;
            foreach (var name in new[] { "TargetPath", "TargetRefPath" })
            {
                var value = project.GetPropertyValue(name);
                if (value.Length != 0)
                {
                    required.Add(Path.GetFullPath(value.Replace('\\', '/'), Path.GetDirectoryName(project.FullPath)!));
                }
            }
            // The runner uses this SDK fallback when TargetRefPath is empty.
            var target = project.GetPropertyValue("TargetPath");
            if (target.Length != 0)
            {
                required.Add(Path.GetFullPath(Path.Combine(project.GetPropertyValue("IntermediateOutputPath").Replace('\\', '/'), "ref", Path.GetFileName(target)), Path.GetDirectoryName(project.FullPath)!));
            }
        }
        foreach (var node in inputs.Graph.ProjectNodes)
        {
            var paths = omitted[node];
            var projectDirectory = Path.GetDirectoryName(node.ProjectInstance.FullPath)!;
            var intermediate = node.ProjectInstance.GetPropertyValue("IntermediateOutputPath").Replace('\\', '/');
            var output = node.ProjectInstance.GetPropertyValue("OutputPath").Replace('\\', '/');
            foreach (var path in paths)
            {
                if (intermediate.Length == 0 || !path.StartsWith(Path.TrimEndingDirectorySeparator(Path.GetFullPath(intermediate, projectDirectory)) + Path.DirectorySeparatorChar, StringComparison.Ordinal) ||
                    (output.Length != 0 && path.StartsWith(Path.TrimEndingDirectorySeparator(Path.GetFullPath(output, projectDirectory)) + Path.DirectorySeparatorChar, StringComparison.Ordinal)) ||
                    !inputs.OwnsOutput(node, path) || required.Contains(path) || Directory.Exists(path) || inputs.OutputDirectories(node).Contains(path, StringComparer.Ordinal))
                {
                    throw new InvalidDataException("Replay omission must be an optional owned file, not a required product: " + Path.GetRelativePath(inputs.Files.Root, path));
                }
            }
        }
    }

    internal bool Contains(ProjectGraphNode node, string path) => omitted[node].Contains(path);
    internal bool HasFiles(ProjectGraphNode node) => omitted[node].Count != 0;

    internal void RequireTargetOutputs(ProjectGraphNode node, IEnumerable<TargetOutput> targets)
    {
        if (omitted[node].Count == 0)
        {
            return;
        }
        foreach (var item in targets.SelectMany(target => target.Items))
        {
            foreach (var value in item.Metadata.Values.Prepend(item.Include).SelectMany(value =>
                value.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)))
            {
                // Metadata such as ReferenceAssembly can name a different result
                // than ItemSpec. Check every literal file path, including relative paths.
                if (value.Length != 0 &&
                    omitted[node].Contains(Path.GetFullPath(value.Replace('\\', '/'), Path.GetDirectoryName(node.ProjectInstance.FullPath)!)))
                {
                    throw new InvalidDataException("Replay omission overlaps target-result metadata: " + value);
                }
            }
        }
    }

    internal void Discard()
    {
        foreach (var path in omitted.Values.SelectMany(paths => paths))
        {
            // Misses produce complete snapshots before optional files are removed.
            inputs.Files.Resolve(Path.GetRelativePath(inputs.Files.Root, path));
            File.Delete(path);
        }
    }
}
