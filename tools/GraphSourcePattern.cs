namespace RulesMSBuild;

// Match Bazel's authored C# globs, excluding output and hidden directories.
internal static class GraphSourcePattern
{
    internal static string Directory(string pattern)
    {
        var parts = pattern.Split('/');
        var directory = parts.Take(parts.Length - (Recursive(pattern) ? 2 : 1)).ToArray();
        if (parts[^1] != "*.cs" || directory.Any(part => part is "" or "." or ".." || ExcludedDirectory(part) ||
            part.IndexOfAny(['*', '?', '[', ']', ':', '\\']) >= 0))
        {
            throw new InvalidDataException("Compile globs require workspace-relative directory/*.cs or directory/**/*.cs patterns: " + pattern);
        }
        return string.Join('/', directory);
    }

    internal static bool Recursive(string pattern) => pattern == "**/*.cs" || pattern.EndsWith("/**/*.cs", StringComparison.Ordinal);

    internal static bool ExcludedDirectory(string name) => name is "bin" or "obj" || name.StartsWith('.') || name.StartsWith("bazel-", StringComparison.Ordinal);

    internal static bool OverlapsDirectory(string pattern, string path)
    {
        var directory = Directory(pattern);
        return directory == path || directory.StartsWith(path + "/", StringComparison.Ordinal) ||
            Recursive(pattern) && Matches(pattern, path + "/Output.cs");
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
        var parts = name.Split('/');
        return !parts[^1].StartsWith('.') && parts[^1].EndsWith(".cs", StringComparison.Ordinal) &&
            (Recursive(pattern) ? !parts.Take(parts.Length - 1).Any(ExcludedDirectory) : parts.Length == 1);
    }

    internal static string[] Members(string root, string pattern, bool checkPackages = false)
    {
        var directory = Directory(pattern);
        var pending = new Stack<string>();
        pending.Push(Path.Combine(root, directory));
        var members = new List<string>();
        while (pending.TryPop(out var physical))
        {
            if (new DirectoryInfo(physical).LinkTarget is not null)
            {
                throw new InvalidDataException("Compile glob crosses a directory link: " + pattern);
            }
            if (!System.IO.Directory.Exists(physical))
            {
                continue;
            }
            if (checkPackages && physical != root && (File.Exists(Path.Combine(physical, "BUILD")) || File.Exists(Path.Combine(physical, "BUILD.bazel"))))
            {
                throw new InvalidDataException("Compile glob crosses a Bazel package: " + pattern);
            }
            members.AddRange(System.IO.Directory.EnumerateFiles(physical)
                .Where(path => path.EndsWith(".cs", StringComparison.Ordinal))
                .Select(path => Path.GetRelativePath(root, path).Replace('\\', '/')));
            if (Recursive(pattern))
            {
                foreach (var child in System.IO.Directory.EnumerateDirectories(physical).Where(path => !ExcludedDirectory(Path.GetFileName(path))))
                {
                    pending.Push(child);
                }
            }
        }
        return members.Order(StringComparer.Ordinal).ToArray();
    }
}
