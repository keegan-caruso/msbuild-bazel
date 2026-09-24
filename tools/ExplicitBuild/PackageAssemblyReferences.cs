using Microsoft.Build.Execution;

// Exact archive-relative assembly declarations, retaining upstream Reference metadata.
internal static class PackageAssemblyReferences
{
    internal static HashSet<string> Validate(Session session, ProjectInstance evaluated)
    {
        var allowed = new HashSet<string>(StringComparer.Ordinal);
        var packages = session.Request.Packages.ToDictionary(p => p.Id, StringComparer.OrdinalIgnoreCase);
        var originals = evaluated.GetItems("_BazelOriginalReference");
        foreach (var (id, paths) in session.Request.PackageReferencePaths ?? [])
        {
            if (!packages.TryGetValue(id, out var package))
            {
                throw new InvalidDataException("Assembly reference requires a locked package: " + id);
            }

            foreach (var path in paths)
            {
                var full = Path.Combine(session.Workspace, ".nuget/packages", package.Id.ToLowerInvariant(), package.Version, Program.Safe(path));
                if (!path.EndsWith(".dll", StringComparison.OrdinalIgnoreCase) || !File.Exists(full))
                {
                    throw new InvalidDataException("Missing declared package assembly: " + id + "/" + path);
                }

                var matches = originals.Where(i => i.EvaluatedInclude == full).ToArray();
                if (matches.Length != 1 || !allowed.Add(full))
                {
                    throw new InvalidDataException("Package assembly requires exactly one matching Reference: " + id + "/" + path);
                }

                foreach (var name in new[] { "HintPath", "Aliases", "EmbedInteropTypes", "ProjectPath" })
                {
                    if (matches[0].GetMetadataValue(name).Length > 0)
                    {
                        throw new InvalidDataException("Unsupported package assembly Reference metadata: " + name);
                    }
                }
            }
        }
        return allowed;
    }
}
