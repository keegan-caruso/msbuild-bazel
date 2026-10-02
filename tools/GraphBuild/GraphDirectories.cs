namespace RulesMSBuild.GraphBuild;

// Directory existence can affect Exists() and SDK discovery even without files.
// These declarations guarantee presence, not recursive ownership of contents.
internal static class GraphDirectories
{
    internal static void Prepare(GraphContract contract, ContractFiles files, bool create)
    {
        var paths = contract.InputDirectories ?? [];
        if (paths.Length != 0 && contract.Version is not (4 or 5 or 6 or 7 or 8))
        {
            throw new InvalidDataException("Input directories require graph contract version 4, 5, 6, 7 or 8");
        }
        var outputPaths = contract.Projects.Values.SelectMany(project => project.OutputDirectories.Concat(project.OutputFiles ?? [])
            .Concat((project.Configurations ?? []).SelectMany(configuration => configuration.OutputDirectories.Concat(configuration.OutputFiles ?? [])))).ToArray();
        foreach (var relative in paths)
        {
            var path = files.Resolve(relative);
            if (relative.Split('/')[0] is ".nuget" or ".package-source" or ".graph-tools" ||
                outputPaths.Any(output => relative == output || relative.StartsWith(output + "/", StringComparison.Ordinal)))
            {
                throw new InvalidDataException("Input directory overlaps generated state: " + relative);
            }
            if (File.Exists(path))
            {
                throw new InvalidDataException("Expected input directory, found file: " + relative);
            }
        }
        foreach (var relative in paths)
        {
            var path = files.Resolve(relative);
            if (create)
            {
                Directory.CreateDirectory(path);
            }
            else if (!Directory.Exists(path))
            {
                throw new InvalidDataException("Declared input directory is missing: " + relative);
            }
        }
    }
}
