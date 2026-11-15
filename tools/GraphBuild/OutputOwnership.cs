namespace RulesMSBuild.GraphBuild;

// One request owns this plan. Paths are validated by ContractFiles before indexing;
// later artifact accesses still resolve paths to catch newly introduced symlinks.
internal sealed class OutputOwnership<TOwner> where TOwner : class
{
    private readonly string root;
    private readonly OutputOwnershipIndex<TOwner> ownership;
    private readonly Dictionary<string, TOwner> directories;
    private readonly Dictionary<string, TOwner> files;
    private readonly string[] inputs;

    internal OutputOwnership(string root, IEnumerable<(TOwner owner, string path)> directories,
        IEnumerable<(TOwner owner, string path)> files, IEnumerable<string> inputs)
    {
        ownership = new OutputOwnershipIndex<TOwner>(directories, files);
        // Keep execution's fail-fast diagnostics and exact-path restrictions.
        this.root = root;
        this.inputs = inputs.Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
        this.directories = SingleOwners(ownership.Directories, "Overlapping output directories: ");
        this.files = SingleOwners(ownership.Files, "Overlapping output file ownership: ");
    }

    internal void Validate()
    {
        foreach (var (path, owner) in files)
        {
            if (directories.ContainsKey(path) || Parents(path).Any(parent => files.ContainsKey(parent) ||
                (directories.TryGetValue(parent, out var other) && !ReferenceEquals(owner, other))))
            {
                throw new InvalidDataException("Overlapping output file ownership: " + path);
            }
            if (Array.BinarySearch(inputs, path, StringComparer.Ordinal) >= 0 || ContainsInput(path))
            {
                throw new InvalidDataException("Output file overlaps a declared input: " + path);
            }
        }
        foreach (var (path, owner) in directories)
        {
            foreach (var parent in Parents(path))
            {
                if (files.ContainsKey(parent))
                {
                    throw new InvalidDataException("Overlapping output file ownership: " + parent);
                }
                if (directories.TryGetValue(parent, out var other) && !ReferenceEquals(owner, other))
                {
                    throw new InvalidDataException("Overlapping output directories: " + path);
                }
            }
            if (ContainsInput(path))
            {
                throw new InvalidDataException("Output directory contains a declared input: " + path);
            }
        }
    }

    internal TOwner? Owner(string path) => ownership.Owners(path, root).FirstOrDefault();

    private bool ContainsInput(string directory)
    {
        // Descendants form one ordinal range beginning at directory + "/".
        // Searching that boundary avoids scanning every input for each output.
        var prefix = directory + "/";
        var index = Array.BinarySearch(inputs, prefix, StringComparer.Ordinal);
        if (index < 0)
        {
            index = ~index;
        }
        return index < inputs.Length && inputs[index].StartsWith(prefix, StringComparison.Ordinal);
    }

    private IEnumerable<string> Parents(string path) => OutputOwnershipIndex<TOwner>.Parents(path, root);

    private static Dictionary<string, TOwner> SingleOwners(IReadOnlyDictionary<string, IReadOnlySet<TOwner>> index, string message) =>
        index.ToDictionary(pair => pair.Key, pair => pair.Value.Count == 1 ? pair.Value.Single() : throw new InvalidDataException(message + pair.Key), StringComparer.Ordinal);
}
