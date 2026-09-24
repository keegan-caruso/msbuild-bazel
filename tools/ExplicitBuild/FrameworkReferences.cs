using Microsoft.Build.Execution;
using NuGet.Frameworks;

internal static class FrameworkReferences
{
    // Bare framework references remain MSBuild references. Their names must be
    // explicit and present in the selected, declared reference pack.
    internal static HashSet<string> ValidateAssemblies(Session session, ProjectInstance evaluated, bool requireReferences = false)
    {
        var request = session.Request;
        var names = (request.FrameworkAssemblies ?? []).ToHashSet(StringComparer.OrdinalIgnoreCase);
        if (names.Count == 0 && evaluated.GetItems("_BazelOriginalReference").Count == 0)
        {
            return names;
        }

        var roots = new List<string>();
        if (request.FrameworkInputs is not null)
        {
            roots.Add(Path.Combine(session.Workspace, ".framework"));
        }

        var framework = NuGetFramework.ParseFolder(request.Framework);
        string PackageRoot(PackageInput package) => Path.Combine(session.Workspace, ".nuget", "packages", package.Id.ToLowerInvariant(), package.Version);
        foreach (var known in evaluated.GetItems("KnownFrameworkReference").Where(i => i.GetMetadataValue("TargetFramework") == request.Framework))
        {
            if (!evaluated.GetItems("FrameworkReference").Any(i => i.EvaluatedInclude.Equals(known.EvaluatedInclude, StringComparison.OrdinalIgnoreCase)))
            {
                continue;
            }

            var id = known.GetMetadataValue("TargetingPackName");
            var version = known.GetMetadataValue("TargetingPackVersion");
            var package = request.Packages.SingleOrDefault(p => p.Id.Equals(id, StringComparison.OrdinalIgnoreCase) && p.Version == version);
            var root = package is null ? Path.Combine(session.Sdk, "packs", Program.Safe(id), Program.Safe(version)) : PackageRoot(package);
            roots.Add(Path.Combine(root, "ref", request.Framework));
        }
        if (framework.Framework == ".NETFramework")
        {
            var package = request.Packages.SingleOrDefault(p => p.Id.Equals("Microsoft.NETFramework.ReferenceAssemblies." + request.Framework, StringComparison.OrdinalIgnoreCase));
            if (package is not null)
            {
                roots.Add(Path.Combine(PackageRoot(package), "build", ".NETFramework", "v" + framework.Version.ToString(framework.Version.Build == 0 ? 2 : 3)));
            }
        }
        if (framework.Framework == ".NETStandard" && framework.Version == new Version(2, 0, 0, 0))
        {
            var package = request.Packages.SingleOrDefault(p => p.Id.Equals("NETStandard.Library", StringComparison.OrdinalIgnoreCase));
            if (package is not null)
            {
                roots.Add(Path.Combine(PackageRoot(package), "build", "netstandard2.0", "ref"));
            }
        }
        var files = roots.Where(Directory.Exists).SelectMany(root => Directory.GetFiles(root, "*.dll")).ToHashSet(StringComparer.Ordinal);
        var available = files.Select(Path.GetFileNameWithoutExtension).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var original = evaluated.GetItems("_BazelOriginalReference");
        foreach (var name in names)
        {
            if (!available.Contains(name))
            {
                throw new InvalidDataException("Assembly is not in a declared framework reference pack: " + name);
            }

            var matches = original.Where(i => i.EvaluatedInclude.Equals(name, StringComparison.OrdinalIgnoreCase)).ToArray();
            if (requireReferences && matches.Length == 0)
            {
                throw new InvalidDataException("Framework assembly requires a matching Reference: " + name);
            }

            foreach (var match in matches)
            {
                foreach (var metadata in new[] { "HintPath", "Aliases", "SpecificVersion", "EmbedInteropTypes" })
                {
                    if (match.GetMetadataValue(metadata).Length > 0)
                    {
                        throw new InvalidDataException("Unsupported framework Reference metadata: " + metadata);
                    }
                }
            }
        }
        names.UnionWith(original.Where(i => files.Contains(i.EvaluatedInclude)).Select(i => i.EvaluatedInclude));
        return names;
    }

    internal static void Validate(Request request)
    {
        if (request.DependencyFrameworks is null)
        {
            return;
        }

        if (!request.DependencyFrameworks.Keys.ToHashSet(StringComparer.Ordinal).SetEquals(request.Dependencies))
        {
            throw new InvalidDataException("Dependency framework declarations disagree with project dependencies");
        }

        static NuGetFramework Parse(string value)
        {
            var framework = NuGetFramework.ParseFolder(value);
            if (framework.IsUnsupported || framework.Equals(NuGetFramework.AnyFramework))
            {
                throw new InvalidDataException("Unsupported explicit framework: " + value);
            }

            return framework;
        }
        var consumer = Parse(request.Framework);
        foreach (var (project, framework) in request.DependencyFrameworks)
        {
            if (!DefaultCompatibilityProvider.Instance.IsCompatible(consumer, Parse(framework)))
            {
                throw new InvalidDataException("Incompatible explicit project frameworks: " + request.Framework + " cannot reference " + framework + " (" + project + ")");
            }
        }
    }
}
