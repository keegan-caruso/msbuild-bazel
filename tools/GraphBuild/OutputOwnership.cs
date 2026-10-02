namespace RulesMSBuild.GraphBuild;

// One request owns this plan. Paths are validated by ContractFiles before indexing;
// later artifact accesses still resolve paths to catch newly introduced symlinks.
internal sealed class OutputOwnership<TOwner> where TOwner : class
{
    private readonly string root;
    private readonly Dictionary<string, TOwner> directories = new(StringComparer.Ordinal);
    private readonly Dictionary<string, TOwner> files = new(StringComparer.Ordinal);
    private readonly string[] inputs;

    internal OutputOwnership(string root, IEnumerable<(TOwner owner, string path)> directories,
        IEnumerable<(TOwner owner, string path)> files, IEnumerable<string> inputs)
    {
        this.root = root;
        this.inputs = inputs.Distinct(StringComparer.Ordinal).Order(StringComparer.Ordinal).ToArray();
        foreach (var (owner, path) in directories)
        {
            Add(this.directories, owner, path, "Overlapping output directories: ");
        }
        foreach (var (owner, path) in files)
        {
            Add(this.files, owner, path, "Overlapping output file ownership: ");
        }
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

    internal TOwner? Owner(string path)
    {
        if (files.TryGetValue(path, out var owner))
        {
            return owner;
        }
        foreach (var parent in Parents(path))
        {
            if (directories.TryGetValue(parent, out owner))
            {
                return owner;
            }
        }
        return null;
    }

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

    private IEnumerable<string> Parents(string path)
    {
        for (var parent = Path.GetDirectoryName(path); parent is not null && parent != root; parent = Path.GetDirectoryName(parent))
        {
            yield return parent;
        }
    }

    private static void Add(Dictionary<string, TOwner> index, TOwner owner, string path, string message)
    {
        if (!index.TryAdd(path, owner) && !ReferenceEquals(index[path], owner))
        {
            throw new InvalidDataException(message + path);
        }
    }
}
