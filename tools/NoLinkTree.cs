namespace RulesMSBuild;

// Keep the two existing contracts distinct: input-tree inventories include
// directories and reject all reparse points, while output inventories return
// files and reject child symlinks. Callers validate output roots separately.
internal static class NoLinkTree
{
    internal static IEnumerable<string> Entries(string root, string error, bool ordered = false) => Walk(root, error, entries: true, ordered);
    internal static IEnumerable<string> Files(string root, string error) => Walk(root, error, entries: false, ordered: false);

    private static IEnumerable<string> Walk(string root, string error, bool entries, bool ordered)
    {
        if (entries && (File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidDataException(error + root);
        }
        var children = Directory.EnumerateFileSystemEntries(root);
        foreach (var path in ordered ? children.Order(StringComparer.Ordinal) : children)
        {
            if (!entries && new FileInfo(path).LinkTarget is not null)
            {
                throw new InvalidDataException(error + path);
            }
            if (Directory.Exists(path))
            {
                if (entries)
                {
                    yield return path;
                }
                foreach (var child in Walk(path, error, entries, ordered))
                {
                    yield return child;
                }
            }
            else
            {
                if (entries && (File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                {
                    throw new InvalidDataException(error + path);
                }
                yield return path;
            }
        }
    }
}
