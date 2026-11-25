using System.Collections.Frozen;

namespace RulesMSBuild;

// Immutable path facts shared by execution and qualification. Callers choose
// whether conflicts reject a graph or merely make its snapshots ineligible.
internal sealed class OutputOwnershipIndex<TOwner> where TOwner : class
{
    internal static StringComparer PathComparer { get; } = OperatingSystem.IsWindows() ? StringComparer.OrdinalIgnoreCase : StringComparer.Ordinal;
    internal static StringComparison PathComparison { get; } = OperatingSystem.IsWindows() ? StringComparison.OrdinalIgnoreCase : StringComparison.Ordinal;
    internal static string CanonicalPath(string path) => OperatingSystem.IsWindows() ? path.Replace('\\', '/') : path;

    internal IReadOnlyDictionary<string, IReadOnlySet<TOwner>> Directories
    {
        get;
    }
    internal IReadOnlyDictionary<string, IReadOnlySet<TOwner>> Files
    {
        get;
    }

    internal OutputOwnershipIndex(IEnumerable<(TOwner owner, string path)> directories, IEnumerable<(TOwner owner, string path)> files)
    {
        Directories = Index(directories);
        Files = Index(files);
    }

    internal IEnumerable<TOwner> Owners(string path, string? boundary = null) =>
        (Files.TryGetValue(CanonicalPath(path), out var exact) ? exact : Enumerable.Empty<TOwner>())
        .Concat(Parents(path, boundary).Where(Directories.ContainsKey).SelectMany(parent => Directories[parent]))
        .Distinct(ReferenceEqualityComparer.Instance).Cast<TOwner>();

    internal HashSet<TOwner> ConflictingOwners()
    {
        var conflicts = new HashSet<TOwner>(ReferenceEqualityComparer.Instance);
        foreach (var (path, owners) in Directories)
        {
            Mark(owners.Concat(Parents(path).Where(Directories.ContainsKey).SelectMany(parent => Directories[parent])));
        }
        foreach (var (path, owners) in Files)
        {
            Mark(owners.Concat(Parents(path).Where(Directories.ContainsKey).SelectMany(parent => Directories[parent])));
        }
        return conflicts;

        void Mark(IEnumerable<TOwner> values)
        {
            var distinct = values.Distinct(ReferenceEqualityComparer.Instance).Cast<TOwner>().ToArray();
            if (distinct.Length > 1)
            {
                conflicts.UnionWith(distinct);
            }
        }
    }

    internal static IEnumerable<string> Parents(string path, string? boundary = null)
    {
        for (var parent = Parent(path); !string.IsNullOrEmpty(parent) && !PathComparer.Equals(parent, boundary is null ? null : CanonicalPath(boundary)); parent = Parent(parent))
        {
            yield return parent;
        }
    }

    private static string? Parent(string path) => Path.GetDirectoryName(path) is { } parent ? CanonicalPath(parent) : null;

    private static IReadOnlyDictionary<string, IReadOnlySet<TOwner>> Index(IEnumerable<(TOwner owner, string path)> entries)
    {
        var index = new Dictionary<string, HashSet<TOwner>>(PathComparer);
        foreach (var (owner, rawPath) in entries)
        {
            var path = CanonicalPath(rawPath);
            if (!index.TryGetValue(path, out var owners))
            {
                index.Add(path, owners = new HashSet<TOwner>(ReferenceEqualityComparer.Instance));
            }
            owners.Add(owner);
        }
        return index.ToFrozenDictionary(pair => pair.Key, pair => (IReadOnlySet<TOwner>)pair.Value.ToFrozenSet<TOwner>(ReferenceEqualityComparer.Instance), PathComparer);
    }
}
