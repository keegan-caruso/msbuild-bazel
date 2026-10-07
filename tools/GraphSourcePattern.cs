namespace RulesMSBuild;

// Match the same flat, authored C# set as Bazel's directory/*.cs glob.
internal static class GraphSourcePattern
{
    internal static string Directory(string pattern)
    {
        var parts = pattern.Split('/');
        if (parts[^1] != "*.cs" || parts.Take(parts.Length - 1).Any(part => part is "" or "." or ".." or "bin" or "obj" ||
            part.StartsWith('.') || part.IndexOfAny(['*', '?', '[', ']', ':', '\\']) >= 0))
        {
            throw new InvalidDataException("Compile globs require a workspace-relative flat directory/*.cs pattern: " + pattern);
        }
        return string.Join('/', parts.Take(parts.Length - 1));
    }

    internal static bool Matches(string pattern, string path)
    {
        var directory = Directory(pattern);
        var prefix = directory.Length == 0 ? "" : directory + "/";
        if (!path.StartsWith(prefix, StringComparison.Ordinal))
        {
            return false;
        }
        var name = path[prefix.Length..];
        return !name.StartsWith('.') && !name.Contains('/') && name.EndsWith(".cs", StringComparison.Ordinal);
    }
}
