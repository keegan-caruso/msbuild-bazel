using ActionRunner;

// One placement decision per dependency artifact. Recorded SDK target results
// point at sealed inputs; only path-bearing SDK manifests and runtime overrides
// still need consumer-local files.
internal sealed record PreparedDependencies(Dictionary<string, string> Sources, HashSet<string> Direct, Dictionary<string, string[]> Closures)
{
    internal static Dictionary<string, string[]> ProjectClosures(IReadOnlyDictionary<string, string[]> projects)
    {
        var closures = new Dictionary<string, string[]>(StringComparer.Ordinal);
        var visiting = new HashSet<string>(StringComparer.Ordinal);
        string[] Visit(string project)
        {
            if (closures.TryGetValue(project, out var found)) return found;
            if (!visiting.Add(project)) throw new InvalidDataException("Cyclic project dependencies");
            var selected = new HashSet<string>(StringComparer.Ordinal) { project };
            foreach (var dependency in projects[project]) selected.UnionWith(Visit(dependency));
            visiting.Remove(project);
            return closures[project] = selected.Order(StringComparer.Ordinal).ToArray();
        }
        foreach (var project in projects.Keys) Visit(project);
        return closures;
    }

    internal static PreparedDependencies Create(Dictionary<string, string> bundles, IReadOnlyDictionary<string, string[]> projects, CompileBoundary.ValidationScope validation)
    {
        var closures = ProjectClosures(projects);
        var inputs = new EvaluatedBoundary.RuntimeInputs(validation.Read);
        var sources = new Dictionary<string, string>(StringComparer.Ordinal);
        var direct = new HashSet<string>(StringComparer.Ordinal);
        var hashes = bundles.Values.SelectMany(bundle => validation.Read(bundle).Select(item => KeyValuePair.Create(Path.Combine(bundle, "artifacts", item.Path), item.Sha256))).ToDictionary(StringComparer.Ordinal);
        foreach (var (project, bundle) in bundles)
        {
            var replacements = EvaluatedBoundary.RuntimeReplacements(bundle, project,
                closures[project].Where(p => p != project).ToDictionary(p => p, p => bundles[p]), inputs: inputs);
            var own = inputs.Get(bundle).Artifacts;
            var needsLocalTree = replacements.Any(pair => hashes[pair.Value] != own[pair.Key].Sha256);
            foreach (var artifact in validation.Read(bundle))
            {
                var source = replacements.GetValueOrDefault(artifact.Path, Path.Combine(bundle, "artifacts", artifact.Path));
                // A transitive runtime contract often already equals its current
                // owner's bytes. Consume that prepared copy without recreating it.
                if (hashes[source] == artifact.Sha256) source = Path.Combine(bundle, "artifacts", artifact.Path);
                if (!sources.TryAdd(artifact.Path, source)) throw new InvalidDataException("Ambiguous dependency artifact ownership");
                // If any adjacent runtime really differs, keep this producer's
                // complete current tree together rather than mixing load roots.
                // Preserve adjacent-file lookup (RAR and analyzer loading) using
                // the producer's original tree. Current-runtime substitutions and
                // workspace-bearing SDK metadata retain the established placement.
                if (!needsLocalTree && !StaticWebAssets.NeedsRebase(artifact.Path) && source == Path.Combine(bundle, "artifacts", artifact.Path)) direct.Add(artifact.Path);
            }
        }
        return new(sources, direct, closures);
    }

    internal string Expand(string value, string workspace)
    {
        const string prefix = "${WORKSPACE}/";
        var path = value.StartsWith(prefix, StringComparison.Ordinal) ? DependencyReplay.UnescapePath(value[prefix.Length..]) : null;
        return path is not null && Direct.Contains(path)
            ? DependencyReplay.EscapePath(Sources[path]) : value.Replace("${WORKSPACE}", workspace, StringComparison.Ordinal);
    }
}
