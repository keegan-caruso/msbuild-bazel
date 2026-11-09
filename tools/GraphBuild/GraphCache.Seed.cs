using Microsoft.Build.Graph;
using RulesMSBuild.ProjectCache;

namespace RulesMSBuild.GraphBuild;

internal sealed partial class GraphCache
{
    internal async Task<int> SeedAsync(BuildSeed seed)
    {
        var records = seed.Projects.ToDictionary(project => project.Key, StringComparer.Ordinal);
        if (!records.Keys.ToHashSet(StringComparer.Ordinal).SetEquals(nodes.Keys))
        {
            throw new InvalidDataException("Qualification seed has different configured projects");
        }
        var selected = new List<(ProjectGraphNode Node, string[] Requested, TargetOutput[] Targets)>();
        foreach (var (key, node) in nodes)
        {
            var record = records[key];
            var actual = BuildSeedProof.Context(node.ProjectInstance);
            RequireEqual(record.Context.Properties, actual.Properties, "properties", key);
            RequireEqual(record.Context.Items, actual.Items, "items", key);
            if (!GraphProjectKind.HasAssembly(node.ProjectInstance) || record.RequestedTargets.Length == 0)
            {
                continue;
            }
            if (!record.RequestedTargets.Contains("Build", StringComparer.OrdinalIgnoreCase) || !record.Targets.Select(target => target.Name).SequenceEqual(ReplayTargets(node, record.RequestedTargets), StringComparer.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Qualification seed has different requested targets: " + key);
            }
            inputs.VerifyCompilerReferences(node, record.References);
            foreach (var path in SnapshotFiles(node).Concat(inputs.DeclaredOutputFiles(node)).Distinct())
            {
                var relative = Path.GetRelativePath(inputs.Files.Root, path);
                if (!seed.Outputs.TryGetValue(relative, out var digest) || BuildSeedProof.Digest(path) != digest)
                {
                    throw new InvalidDataException("Qualification seed omits or changes an owned output: " + relative);
                }
            }
            var targets = record.Targets.Select(target => new TargetOutput(target.Name,
                target.Items.Select(item => new ResultItem(item.Include, item.Metadata)).ToArray())).ToArray();
            omissions.RequireTargetOutputs(node, targets);
            selected.Add((node, record.RequestedTargets, targets));
        }
        // Validate every project before making any graph-cache entry visible.
        inputs.VerifyUnchangedInputs();
        foreach (var (node, requested, targets) in selected)
        {
            var key = GraphInputs.Key(node.ProjectInstance);
            fingerprints[key] = Fingerprint(node, requested);
            requestedTargets[key] = requested;
            await CaptureAsync(node, () => targets);
        }
        return selected.Count;
    }

    private static void RequireEqual(Dictionary<string, string> expected, Dictionary<string, string> actual, string kind, string key)
    {
        var changed = expected.Keys.Union(actual.Keys, StringComparer.Ordinal)
            .Where(name => expected.GetValueOrDefault(name) != actual.GetValueOrDefault(name)).ToArray();
        if (changed.Length != 0)
        {
            throw new InvalidDataException("Qualification seed has different evaluated " + kind + " for " + key + ": " + string.Join(", ", changed.Take(8)));
        }
    }
}
