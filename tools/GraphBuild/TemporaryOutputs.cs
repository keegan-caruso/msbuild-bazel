using Microsoft.Build.Graph;

namespace RulesMSBuild.GraphBuild;

// Reviewed task scratch is discarded only after input verification and before
// cache publication. Required products and replayed results must never point here.
internal sealed class TemporaryOutputs
{
    private readonly GraphInputs inputs;
    private readonly string[] relatives;
    private readonly string[] paths;

    internal TemporaryOutputs(GraphContract contract, GraphInputs inputs)
    {
        this.inputs = inputs;
        relatives = contract.TemporaryDirectories ?? [];
        if (relatives.Length != 0 && contract.Version is not (5 or 6 or 7 or 8 or 9 or 10 or 11))
        {
            throw new InvalidDataException("Temporary directories require graph contract version 5, 6, 7, 8, 9, 10 or 11");
        }
        paths = relatives.Select(inputs.Files.Resolve).Distinct(StringComparer.Ordinal).ToArray();
        if (paths.Length == 0)
        {
            return;
        }
        var nodes = inputs.Graph.ProjectNodes;
        var directories = nodes.SelectMany(inputs.OutputDirectories).ToArray();
        var required = contract.SharedInputs.Concat(nodes.SelectMany(node => inputs.For(node).Inputs))
            .Concat(contract.InputDirectories ?? []).Select(inputs.Files.Resolve)
            .Concat(nodes.SelectMany(node => (inputs.For(node).DependencyCopies ?? [])
                .SelectMany(copy => new[] { copy.Key, copy.Value })).Select(inputs.Files.Resolve))
            .Concat(nodes.SelectMany(inputs.DeclaredOutputFiles))
            .Concat(nodes.SelectMany(node => (inputs.For(node).CompilerReferences ?? []).Values).Select(inputs.Files.Resolve))
            .Concat(nodes.Select(node => inputs.For(node).CompilerReference).Where(path => path is not null).Select(path => inputs.Files.Resolve(path!)))
            .Concat(nodes.SelectMany(node => new[] { "TargetPath", "TargetRefPath" }
                .Select(node.ProjectInstance.GetPropertyValue).Where(path => path.Length != 0)
                .Select(path => Path.GetFullPath(path.Replace('\\', '/'), Path.GetDirectoryName(node.ProjectInstance.FullPath)!))))
            .Concat(nodes.SelectMany(node => node.ProjectInstance.GetItems("IntermediateAssembly")
                .Concat(node.ProjectInstance.GetItems("IntermediateRefAssembly"))
                .Select(item => Path.GetFullPath(item.EvaluatedInclude.Replace('\\', '/'), Path.GetDirectoryName(node.ProjectInstance.FullPath)!))))
            .Distinct(StringComparer.Ordinal).ToArray();
        foreach (var path in paths)
        {
            if (!directories.Any(directory => Inside(path, directory)))
            {
                throw new InvalidDataException("Temporary directory must be a strict child of an owned output directory: " + path);
            }
            if (required.Any(value => value == path || Inside(value, path)))
            {
                throw new InvalidDataException("Temporary directory overlaps an input or required product: " + path);
            }
            if (paths.Any(other => other != path && Inside(path, other)))
            {
                throw new InvalidDataException("Temporary directory declarations must not overlap: " + path);
            }
            if (File.Exists(path))
            {
                throw new InvalidDataException("Temporary directory is a file: " + path);
            }
        }
    }

    internal bool Contains(string path) => paths.Any(temporary => path == temporary || Inside(path, temporary));

    internal int Discard(GraphBuildResult result)
    {
        if (paths.Length == 0)
        {
            return 0;
        }
        // Validate every path and result before deleting anything. A target may
        // introduce links during execution or return a path in item metadata.
        foreach (var relative in relatives)
        {
            var path = inputs.Files.Resolve(relative);
            if (File.Exists(path))
            {
                throw new InvalidDataException("Temporary directory is a file: " + path);
            }
        }
        foreach (var (node, build) in result.ResultsByNode)
        {
            var directory = Path.GetDirectoryName(node.ProjectInstance.FullPath)!;
            foreach (var target in build.ResultsByTarget.Values)
            {
                foreach (var item in target.Items)
                {
                    foreach (var value in new[] { item.ItemSpec }.Concat(item.MetadataNames.Cast<string>().Select(item.GetMetadata)))
                    {
                        foreach (var candidate in value.Split(';', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
                        {
                            string path;
                            try
                            {
                                path = Path.GetFullPath(candidate.Replace('\\', '/'), directory);
                            }
                            catch (Exception error) when (error is ArgumentException or NotSupportedException)
                            {
                                continue;
                            }
                            if (Contains(path))
                            {
                                throw new InvalidDataException("Target result references a temporary directory: " + candidate);
                            }
                        }
                    }
                }
            }
        }
        var removed = 0;
        foreach (var path in paths)
        {
            if (Directory.Exists(path))
            {
                Directory.Delete(path, recursive: true);
                removed++;
            }
        }
        return removed;
    }

    private static bool Inside(string path, string directory) => path.StartsWith(directory + Path.DirectorySeparatorChar, StringComparison.Ordinal);
}
