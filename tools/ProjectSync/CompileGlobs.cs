using Microsoft.Build.Execution;

namespace RulesMSBuild.ProjectSync;

internal static class CompileGlobs
{
    internal static string[] Qualify(string root, string evaluationRoot, ProjectInstance project, ProjectBinding binding,
        IEnumerable<string> fixedInputs, IEnumerable<string> reserved, IEnumerable<string> outputs, IEnumerable<string> outputDirectories, IEnumerable<string> boundPaths)
    {
        var patterns = binding.CompileGlobs.Order(StringComparer.Ordinal).ToArray();
        if (patterns.Length == 0)
        {
            return patterns;
        }
        if (project.GetPropertyValue("Language") != "C#")
        {
            throw new InvalidDataException("Compile globs require a C# project: " + project.FullPath);
        }
        string Relative(string path) => Path.GetRelativePath(evaluationRoot, Path.GetFullPath(path.Replace('\\', '/'), Path.GetDirectoryName(project.FullPath)!)).Replace('\\', '/');
        var compiler = project.GetItems("Compile").Select(item => Relative(item.EvaluatedInclude)).ToHashSet(StringComparer.Ordinal);
        var other = new[] { "EmbeddedResource", "Content", "None", "AdditionalFiles", "Analyzer", "EditorConfigFiles", "GlobalAnalyzerConfigFiles", "RazorGenerate" }
            .Concat(binding.InputItems.Keys).SelectMany(project.GetItems).Select(item => Relative(item.EvaluatedInclude))
            .Concat(fixedInputs).Concat(reserved).Concat(outputs).Concat(boundPaths).ToArray();
        foreach (var pattern in patterns)
        {
            var directory = GraphSourcePattern.Directory(pattern);
            if (SourceGlobs.HasPackageOrLink(root, directory) ||
                outputDirectories.Any(path => directory == path || directory.StartsWith(path + "/", StringComparison.Ordinal)))
            {
                throw new InvalidDataException("Compile glob overlaps a package, link or owned output: " + pattern);
            }
            var physical = Path.Combine(root, directory);
            var members = Directory.Exists(physical) ? Directory.EnumerateFiles(physical)
                .Where(path => path.EndsWith(".cs", StringComparison.Ordinal))
                .Select(path => Path.GetRelativePath(root, path).Replace('\\', '/')).ToArray() : [];
            if (members.Any(path => Path.GetFileName(path).StartsWith('.') ||
                    (File.GetAttributes(Path.Combine(root, path)) & FileAttributes.ReparsePoint) != 0) ||
                !members.ToHashSet(StringComparer.Ordinal).SetEquals(compiler.Where(path => GraphSourcePattern.Matches(pattern, path))) ||
                other.Any(path => GraphSourcePattern.Matches(pattern, path)))
            {
                throw new InvalidDataException("Compile glob must select exactly authored Compile-only files: " + pattern);
            }
        }
        return patterns;
    }
}
