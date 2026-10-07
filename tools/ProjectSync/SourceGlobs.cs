namespace RulesMSBuild.ProjectSync;

// Compact repeated directory prefixes, retaining exact membership for analysis.
internal sealed record SourceGlobs(string Declaration, string Expression, string Load)
{
    internal static SourceGlobs Create(string root, string[] sources, IEnumerable<string> compilerSources, string[]? compileGlobs = null)
    {
        compileGlobs ??= [];
        var literal = StarlarkLiteral.Serialize(sources);
        sources = sources.Where(path => !compileGlobs.Any(pattern => GraphSourcePattern.Matches(pattern, path))).ToArray();
        var explicitFiles = sources.ToHashSet(StringComparer.Ordinal);
        var patterns = new SortedDictionary<string, string[]>(StringComparer.Ordinal);
        foreach (var group in compilerSources.Intersect(sources, StringComparer.Ordinal)
            .Where(path => path.EndsWith(".cs", StringComparison.Ordinal))
            .GroupBy(path => Path.GetDirectoryName(path)!.Replace('\\', '/'))
            .OrderBy(group => group.Key, StringComparer.Ordinal))
        {
            var directory = group.Key;
            if (directory.Length == 0 || directory.Split('/').Any(part => part is "bin" or "obj" || part.StartsWith('.')) ||
                directory.IndexOfAny(['*', '?', '[', ']', ':']) >= 0 || HasPackageOrLink(root, directory))
            {
                continue;
            }
            var wanted = group.Distinct().Order(StringComparer.Ordinal).ToArray();
            var physical = Path.Combine(root, directory);
            if (!Directory.Exists(physical))
            {
                continue;
            }
            var matches = Directory.EnumerateFiles(physical)
                .Where(path => path.EndsWith(".cs", StringComparison.Ordinal))
                .Select(path => directory + "/" + Path.GetFileName(path)).Order(StringComparer.Ordinal).ToArray();
            // Bazel's compound *.cs pattern does not match dot-prefixed files.
            if (!matches.SequenceEqual(wanted) || matches.Any(path => Path.GetFileName(path).StartsWith('.') ||
                (File.GetAttributes(Path.Combine(root, path)) & FileAttributes.ReparsePoint) != 0))
            {
                continue;
            }
            var names = wanted.Select(path => Path.GetFileName(path)!).ToArray();
            var pattern = directory + "/*.cs";
            if (StarlarkLiteral.Serialize(new Dictionary<string, string[]> { [pattern] = names }).Length >= StarlarkLiteral.Serialize(wanted).Length)
            {
                continue;
            }
            patterns.Add(pattern, names);
            explicitFiles.ExceptWith(wanted);
        }
        var load = "load(\"@rules_msbuild//msbuild:sync.bzl\", \"sync_source_globs\")\n";
        var declaration = "    sync_source_globs(name = name + \"_sources\", globs = " + StarlarkLiteral.Serialize(patterns) + (compileGlobs.Length == 0 ? "" : ", compile_globs = " + StarlarkLiteral.Serialize(compileGlobs)) + ")\n";
        var expression = StarlarkLiteral.Serialize(explicitFiles.Order(StringComparer.Ordinal).ToArray()) + " + [\":\" + name + \"_sources\"]";
        return compileGlobs.Length != 0 || patterns.Count != 0 && declaration.Length + expression.Length + load.Length < literal.Length
            ? new(declaration, expression, load) : new("", literal, "");
    }

    internal static bool HasPackageOrLink(string root, string directory)
    {
        if (directory.Length == 0)
        {
            return false;
        }
        var current = root;
        foreach (var part in directory.Split('/'))
        {
            current = Path.Combine(current, part);
            if (new FileInfo(current).LinkTarget is not null || new DirectoryInfo(current).LinkTarget is not null)
            {
                return true;
            }
            if (!Directory.Exists(current))
            {
                return false;
            }
            if (File.Exists(Path.Combine(current, "BUILD")) || File.Exists(Path.Combine(current, "BUILD.bazel")))
            {
                return true;
            }
        }
        return false;
    }
}
