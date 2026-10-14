namespace RulesMSBuild.GraphBuild;

// Tree membership is a reviewed sync contract. Bytes participate in SharedInputs;
// newly added files must not silently bypass project-cache fingerprints.
internal static class GraphTrees
{
    internal static void Verify(GraphContract contract, ContractFiles files)
    {
        if (contract.InputTrees?.Count is not > 0)
        {
            return;
        }
        if (contract.Version != 12)
        {
            throw new InvalidDataException("Input trees require graph contract version 12");
        }
        var shared = contract.SharedInputs.ToHashSet(StringComparer.Ordinal);
        foreach (var (root, tree) in contract.InputTrees)
        {
            var directory = files.Resolve(root);
            var expected = tree.Files.Concat(tree.Directories).ToArray();
            if (!Directory.Exists(directory) || expected.Distinct(StringComparer.Ordinal).Count() != expected.Length ||
                expected.Any(path => !path.StartsWith(root + "/", StringComparison.Ordinal) || (!tree.Directories.Contains(path, StringComparer.Ordinal) && !shared.Contains(path))))
            {
                throw new InvalidDataException("Input tree requires declared members: " + root);
            }
            var actual = Members(directory).Select(path => root + "/" + Path.GetRelativePath(directory, path).Replace('\\', '/'));
            if (!actual.ToHashSet(StringComparer.Ordinal).SetEquals(expected) ||
                tree.Directories.Any(path => !Directory.Exists(files.Resolve(path))) || tree.Files.Any(path => !File.Exists(files.Resolve(path))))
            {
                throw new InvalidDataException("Input tree membership changed; rerun sync: " + root);
            }
        }
    }

    private static IEnumerable<string> Members(string root)
    {
        if ((File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidDataException("Input tree symlinks are unsupported: " + root);
        }
        foreach (var entry in Directory.EnumerateFileSystemEntries(root))
        {
            if (Directory.Exists(entry))
            {
                yield return entry;
                foreach (var path in Members(entry))
                {
                    yield return path;
                }
            }
            else if ((File.GetAttributes(entry) & FileAttributes.ReparsePoint) != 0)
            {
                throw new InvalidDataException("Input tree symlinks are unsupported: " + entry);
            }
            else
            {
                yield return entry;
            }
        }
    }
}
