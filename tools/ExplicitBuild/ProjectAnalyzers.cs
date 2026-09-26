using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.Build.Execution;

internal static class ProjectAnalyzers
{
    private static IEnumerable<string> Paths(Request request, string workspace, string[]? roots) =>
        (request.ProjectAnalyzers ?? []).Select((a, i) => Path.Combine(roots is null ? Path.Combine(workspace, ".analyzers", i.ToString(System.Globalization.CultureInfo.InvariantCulture)) : roots[i], Program.Safe(a.Assembly)));

    // Stable tool paths reuse Roslyn's loaded analyzer closure across consumer edits.
    // The broker recreates only this request's declared files under its read-only
    // input mount. Include every closure file so helper/resource changes invalidate
    // the complete load group; never merge registrations from different groups.
    internal static string[] WorkerRoots(Request request, string root, Func<string, string> digest) =>
        (request.ProjectAnalyzers ?? []).Select(analyzer =>
        {
            var files = analyzer.Directories.SelectMany(directory => RuntimePackages.Files(directory, analyzer.Packages ?? []))
                .Select(file => file.Path + ":" + digest(file.Source)).Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
            var identity = JsonSerializer.Serialize(new
            {
                version = 1,
                analyzer.Assembly,
                files
            });
            return Path.Combine(root, Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(identity))));
        }).ToArray();

    internal static IEnumerable<string> CompilerInputs(Request request, string workspace, string[]? roots = null)
    {
        // Roslyn registers dependency locations from /analyzer inputs; merely
        // placing a helper next to the entry assembly does not register it.
        foreach (var entry in Paths(request, workspace, roots))
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

    internal static void Stage(Request request, string workspace, string[]? roots = null)
    {
        var paths = Paths(request, workspace, roots).ToArray();
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
            var skipReference = dependency.GetMetadataValue("SkipUseReferenceAssembly");
            if (skipReference.Length != 0 && (!bool.TryParse(skipReference, out var skip) || skip && !(request.ImplementationReferences ?? []).Contains(Logical(dependency))))
            {
                throw new InvalidDataException("SkipUseReferenceAssembly requires an implementation-reference producer: " + Logical(dependency));
            }
            if (request.Dependencies.Contains(Logical(dependency)))
            {
                var privateAssets = dependency.GetMetadataValue("PrivateAssets").ToLowerInvariant();
                var implementation = (request.ImplementationDependencies ?? []).Contains(Logical(dependency));
                if (implementation ? privateAssets != "all" : privateAssets is not ("" or "none"))
                {
                    throw new InvalidDataException("ProjectReference PrivateAssets disagrees with Bazel implementation_deps: " + Logical(dependency));
                }
            }
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
