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
        {
            foreach (var file in Directory.GetFiles(Path.GetDirectoryName(entry)!, "*.dll"))
            {
                try
                {
                    System.Reflection.AssemblyName.GetAssemblyName(file);
                }
                catch (BadImageFormatException) { continue; }
                yield return file;
            }
        }
    }

    internal static void Stage(Request request, string workspace)
    {
        var paths = Paths(request, workspace).ToArray();
        for (var i = 0; i < paths.Length; i++)
        {
            var analyzer = request.ProjectAnalyzers![i];
            if (analyzer.Assembly.Contains('/'))
            {
                throw new InvalidDataException("Analyzer assembly must be a filename");
            }

            var destination = Path.GetDirectoryName(paths[i])!;
            foreach (var directory in analyzer.Directories)
            {
                foreach (var file in RuntimePackages.Files(directory, analyzer.Packages ?? []))
                {
                    var target = Path.Combine(destination, Program.Safe(file.Path));
                    Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                    if (File.Exists(target))
                    {
                        if (!File.ReadAllBytes(file.Source).AsSpan().SequenceEqual(File.ReadAllBytes(target)))
                        {
                            throw new InvalidDataException("Conflicting analyzer dependency: " + target);
                        }
                    }
                    else
                    {
                        File.Copy(file.Source, target);
                    }
                }
            }

            if (!File.Exists(paths[i]))
            {
                throw new InvalidDataException("Missing analyzer implementation: " + analyzer.Assembly);
            }
        }
    }

    internal static void Validate(Session s, ProjectInstance evaluated)
    {
        var request = s.Request;
        var analyzers = (request.ProjectAnalyzers ?? []).Select(a => a.Project).ToHashSet(StringComparer.Ordinal);
        var tools = (request.BuildTools ?? []).Select(t => t.Project).ToHashSet(StringComparer.Ordinal);
        var outputs = (request.ProjectOutputs ?? []).ToDictionary(p => p.Project, StringComparer.Ordinal);
        if (outputs.Keys.Any(p => tools.Contains(p) || analyzers.Contains(p) || request.Dependencies.Contains(p)))
        {
            throw new InvalidDataException("Project output roles must be separate from compile, tool and analyzer roles");
        }

        if (tools.Overlaps(analyzers))
        {
            throw new InvalidDataException("Tool projects cannot also be analyzers");
        }

        if (analyzers.Overlaps(request.Dependencies))
        {
            throw new InvalidDataException("Project cannot be both an analyzer and a compile dependency");
        }

        var directory = Path.GetDirectoryName(Path.Combine(s.Workspace, request.Project.Path))!;
        string Logical(ProjectItemInstance item) => Path.GetRelativePath(s.Workspace, Path.GetFullPath(item.EvaluatedInclude.Replace('\\', '/'), directory));
        var original = evaluated.GetItems("_BazelOriginalProjectReference");
        if (!original.Select(Logical).Where(p => !tools.Contains(p) || request.Dependencies.Contains(p)).ToHashSet(StringComparer.Ordinal).SetEquals(request.Dependencies.Concat(analyzers).Concat(outputs.Keys)))
        {
            throw new InvalidDataException("ProjectReference declarations disagree with Bazel deps/analyzers");
        }

        foreach (var dependency in original)
        {
            foreach (var name in new[] { "Aliases" })
            {
                if (dependency.GetMetadataValue(name).Length > 0)
                {
                    throw new InvalidDataException("Unsupported ProjectReference metadata: " + name);
                }
            }

            ConfiguredDependencies.Validate(request, dependency, Logical(dependency), evaluated);
            var build = dependency.GetMetadataValue("BuildReference");
            if (build.Length > 0 && !build.Equals("true", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Unsupported ProjectReference metadata: BuildReference");
            }

            if (outputs.TryGetValue(Logical(dependency), out var projectOutput))
            {
                ProjectOutputs.Validate(projectOutput, dependency);
                continue;
            }
            var analyzer = analyzers.Contains(Logical(dependency));
            var tool = tools.Contains(Logical(dependency)) && !request.Dependencies.Contains(Logical(dependency));
            var output = dependency.GetMetadataValue("OutputItemType");
            var reference = dependency.GetMetadataValue("ReferenceOutputAssembly");
            if (tool ? output.Length > 0 || !reference.Equals("false", StringComparison.OrdinalIgnoreCase)
                : analyzer ? !output.Equals("Analyzer", StringComparison.OrdinalIgnoreCase) || !reference.Equals("false", StringComparison.OrdinalIgnoreCase)
                : output.Length > 0 || reference.Length > 0 && !reference.Equals("true", StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("ProjectReference analyzer role disagrees with Bazel declaration");
            }
        }
    }
}
