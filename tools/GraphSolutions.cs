namespace RulesMSBuild;

// MSBuild regenerates these globals from the declared solution at its current root.
internal static class GraphSolutions
{
    internal static bool IsSolution(string path) => new[] { ".sln", ".slnx" }.Contains(Path.GetExtension(path), StringComparer.OrdinalIgnoreCase);

    internal static bool DerivedProperty(string name) => new[]
        { "SolutionDir", "SolutionPath", "SolutionName", "SolutionFileName", "SolutionExt", "CurrentSolutionConfigurationContents" }
        .Contains(name, StringComparer.OrdinalIgnoreCase);

    internal static bool Validate(string root, IEnumerable<string> entries, IEnumerable<string> properties)
    {
        var paths = entries.ToArray();
        if (paths.Any(path => Path.GetExtension(path).Equals(".slnf", StringComparison.OrdinalIgnoreCase)))
        {
            throw new InvalidDataException("Solution filters are not qualified; select a .sln or .slnx");
        }
        var solutions = paths.Where(IsSolution).ToArray();
        if (solutions.Length == 0)
        {
            return false;
        }
        if (paths.Length != 1 || properties.Any(name => DerivedProperty(name)))
        {
            throw new InvalidDataException("Select one solution entry, without overriding derived solution properties");
        }
        var solution = Path.GetFullPath(solutions[0], root);
        if (!solution.StartsWith(root + Path.DirectorySeparatorChar, StringComparison.Ordinal))
        {
            throw new InvalidDataException("Solution entry must be inside the workspace");
        }
        for (var directory = Path.GetDirectoryName(solution)!; ; directory = Path.GetDirectoryName(directory)!)
        {
            if (Directory.GetFiles(directory).Any(path => Path.GetFileName(path) is "Directory.Solution.props" or "Directory.Solution.targets" ||
                Path.GetFileName(path).Equals("before." + Path.GetFileName(solution) + ".targets", StringComparison.OrdinalIgnoreCase) ||
                Path.GetFileName(path).Equals("after." + Path.GetFileName(solution) + ".targets", StringComparison.OrdinalIgnoreCase)))
            {
                throw new InvalidDataException("Custom solution build hooks are not qualified for project graph builds");
            }
            if (directory == root)
            {
                break;
            }
        }
        return true;
    }
}
