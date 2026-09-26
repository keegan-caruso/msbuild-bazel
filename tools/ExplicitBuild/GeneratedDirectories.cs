using static Program;

// Source-relative SDK outputs live in writable action state, never in input files.
internal static class GeneratedDirectories
{
    private static string Root(string state, string source) => Path.Combine(state, "generated-directories", Safe(source));

    internal static void Prepare(Request request, string workspace, string state, Func<string, string> compilerPath)
    {
        var mappings = request.GeneratedDirectories ?? [];
        ValidatePaths(mappings.Keys);
        ValidatePaths(mappings.Values);
        foreach (var source in mappings.Keys)
        {
            var path = Path.Combine(workspace, source);
            for (var ancestor = path; ancestor != workspace; ancestor = Path.GetDirectoryName(ancestor)!)
            {
                if (File.Exists(ancestor) || new DirectoryInfo(ancestor).LinkTarget is not null)
                {
                    throw new InvalidDataException("Generated directory overlaps an input or link: " + source);
                }
            }
            if (Directory.Exists(path))
            {
                if (Directory.EnumerateFileSystemEntries(path).Any())
                {
                    throw new InvalidDataException("Generated directory overlaps inputs: " + source);
                }
                Directory.Delete(path);
            }
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            var output = Root(state, source);
            Directory.CreateDirectory(output);
            Directory.CreateSymbolicLink(path, compilerPath(output));
        }
    }

    private static void ValidatePaths(IEnumerable<string> paths)
    {
        var seen = new List<string>();
        foreach (var path in paths)
        {
            Safe(path);
            if (path.Split('/').Any(part => part.StartsWith('.')) || seen.Any(other => path.Equals(other, StringComparison.OrdinalIgnoreCase) || path.StartsWith(other + "/", StringComparison.OrdinalIgnoreCase) || other.StartsWith(path + "/", StringComparison.OrdinalIgnoreCase)))
            {
                throw new InvalidDataException("Reserved or overlapping generated directory: " + path);
            }
            seen.Add(path);
        }
    }

    internal static void Publish(Request request, string state, string runtime)
    {
        foreach (var (source, destination) in request.GeneratedDirectories ?? [])
        {
            var root = Root(state, source);
            var output = Path.Combine(runtime, Safe(destination));
            if (File.Exists(output) || Directory.Exists(output))
            {
                throw new InvalidDataException("Generated directory conflicts with runtime output: " + destination);
            }
            CopyTree(root, output);
        }
    }

    private static void CopyTree(string source, string destination)
    {
        if (File.GetAttributes(source).HasFlag(FileAttributes.ReparsePoint))
        {
            throw new InvalidDataException("Generated directory contains a link");
        }
        Directory.CreateDirectory(destination);
        foreach (var entry in Directory.EnumerateFileSystemEntries(source))
        {
            var attributes = File.GetAttributes(entry);
            if (attributes.HasFlag(FileAttributes.ReparsePoint))
            {
                throw new InvalidDataException("Generated directory contains a link");
            }
            var target = Path.Combine(destination, Path.GetFileName(entry));
            if (attributes.HasFlag(FileAttributes.Directory))
            {
                CopyTree(entry, target);
            }
            else
            {
                Copy(entry, target);
            }
        }
    }
}
