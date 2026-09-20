using Microsoft.Build.Execution;

internal static class ProjectAnalyzers
{
    internal static IEnumerable<string> Paths(Request request, string workspace) =>
        (request.ProjectAnalyzers ?? []).Select((a, i) => Path.Combine(workspace, ".analyzers", i.ToString(System.Globalization.CultureInfo.InvariantCulture), Program.Safe(a.Assembly)));

    internal static IEnumerable<string> CompilerInputs(Request request, string workspace)
    {
        // Roslyn registers dependency locations from /analyzer inputs; merely
        // placing a helper next to the entry assembly does not register it.
        foreach (var entry in Paths(request, workspace))
            foreach (var file in Directory.GetFiles(Path.GetDirectoryName(entry)!, "*.dll"))
            {
                try { System.Reflection.AssemblyName.GetAssemblyName(file); }
                catch (BadImageFormatException) { continue; }
                yield return file;
            }
    }

    internal static void Stage(Request request, string workspace)
    {
        var paths = Paths(request, workspace).ToArray();
        for (var i = 0; i < paths.Length; i++)
        {
            var analyzer = request.ProjectAnalyzers![i];
            if (analyzer.Assembly.Contains('/')) throw new InvalidDataException("Analyzer assembly must be a filename");
            var destination = Path.GetDirectoryName(paths[i])!;
            foreach (var directory in analyzer.Directories)
                foreach (var file in Directory.GetFiles(directory, "*", SearchOption.AllDirectories))
                {
                    var target = Path.Combine(destination, Program.Safe(Path.GetRelativePath(directory, file)));
                    Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                    if (File.Exists(target))
                    {
                        if (!File.ReadAllBytes(file).AsSpan().SequenceEqual(File.ReadAllBytes(target))) throw new InvalidDataException("Conflicting analyzer dependency: " + target);
                    }
                    else File.Copy(file, target);
                }
            if (!File.Exists(paths[i])) throw new InvalidDataException("Missing analyzer implementation: " + analyzer.Assembly);
        }
    }

    internal static void Validate(Session s, ProjectInstance evaluated)
    {
        var request = s.Request;
        var analyzers = (request.ProjectAnalyzers ?? []).Select(a => a.Project).ToHashSet(StringComparer.Ordinal);
        if (analyzers.Overlaps(request.Dependencies)) throw new InvalidDataException("Project cannot be both an analyzer and a compile dependency");
        var directory = Path.GetDirectoryName(Path.Combine(s.Workspace, request.Project.Path))!;
        string Logical(ProjectItemInstance item) => Path.GetRelativePath(s.Workspace, Path.GetFullPath(item.EvaluatedInclude.Replace('\\', '/'), directory));
        var original = evaluated.GetItems("_BazelOriginalProjectReference");
        if (!original.Select(Logical).ToHashSet(StringComparer.Ordinal).SetEquals(request.Dependencies.Concat(analyzers)))
            throw new InvalidDataException("ProjectReference declarations disagree with Bazel deps/analyzers");
        foreach (var dependency in original)
        {
            foreach (var name in new[] { "Aliases", "SetTargetFramework", "SetConfiguration", "AdditionalProperties", "GlobalPropertiesToRemove" })
                if (dependency.GetMetadataValue(name).Length > 0) throw new InvalidDataException("Unsupported ProjectReference metadata: " + name);
            var analyzer = analyzers.Contains(Logical(dependency));
            var output = dependency.GetMetadataValue("OutputItemType");
            var reference = dependency.GetMetadataValue("ReferenceOutputAssembly");
            if (analyzer ? !output.Equals("Analyzer", StringComparison.OrdinalIgnoreCase) || !reference.Equals("false", StringComparison.OrdinalIgnoreCase)
                : output.Length > 0 || reference.Length > 0 && !reference.Equals("true", StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("ProjectReference analyzer role disagrees with Bazel declaration");
            var build = dependency.GetMetadataValue("BuildReference");
            if (build.Length > 0 && !build.Equals("true", StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException("Unsupported ProjectReference metadata: BuildReference");
        }
    }
}
