internal static class GitInputs
{
    // Standalone local Git metadata only. Re-evaluation discovers new refs or
    // objects before preparation publishes a graph. Logs/hooks are not build
    // inputs; index/tree/refs/config/shallow state retain SCM and MinVer behavior.
    public static IEnumerable<string> Discover(string workspace)
    {
        var root = Path.Combine(workspace, ".git");
        if (File.Exists(root))
            throw new ExportException("unsupported-git-input", "Git worktree indirection requires a standalone source snapshot");
        if (!Directory.Exists(root)) yield break;
        NoLinks(root);
        foreach (var entry in Directory.EnumerateFileSystemEntries(root)) NoLinks(entry);
        foreach (var unsupported in new[] { "commondir", "config.worktree", "objects/info/alternates", "objects/info/http-alternates" })
            if (File.Exists(Path.Combine(root, unsupported)) || Directory.Exists(Path.Combine(root, unsupported)))
                throw new ExportException("unsupported-git-input", "external Git metadata is not supported: " + unsupported);
        if (Directory.EnumerateFiles(root, "sharedindex.*").Any())
            throw new ExportException("unsupported-git-input", "split Git index is not supported");
        foreach (var required in new[] { "HEAD", "config", "index" })
            if (!File.Exists(Path.Combine(root, required)))
                throw new ExportException("unsupported-git-input", "standalone Git input missing: " + required);
        foreach (var name in new[] { "HEAD", "config", "index", "packed-refs", "shallow", "info/grafts", "info/exclude", "info/attributes" })
        {
            var path = Path.Combine(root, name);
            if (!File.Exists(path)) continue;
            NoLinks(path);
            NoLinks(Path.GetDirectoryName(path)!);
            if (name == "config") ValidateConfig(File.ReadAllText(path));
            yield return path;
        }
        foreach (var name in new[] { "objects", "refs" })
        {
            var directory = Path.Combine(root, name);
            if (!Directory.Exists(directory)) continue;
            foreach (var entry in Walk(directory)) yield return entry;
        }
    }

    private static IEnumerable<string> Walk(string directory)
    {
        NoLinks(directory);
        foreach (var entry in Directory.EnumerateFileSystemEntries(directory))
        {
            NoLinks(entry);
            if (Directory.Exists(entry))
                foreach (var child in Walk(entry)) yield return child;
            else if (File.Exists(entry)) yield return entry;
        }
    }

    private static void NoLinks(string path)
    {
        if ((System.IO.File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
            throw new ExportException("unsupported-git-input", "Git symlink inputs are not supported: " + path);
    }

    private static void ValidateConfig(string config)
    {
        var section = "";
        foreach (var raw in config.Split('\n'))
        {
            var line = raw.Trim();
            if (line.Length == 0 || line.StartsWith('#') || line.StartsWith(';')) continue;
            if (line.StartsWith('['))
            {
                section = line.ToLowerInvariant();
                if (section != "[core]" && !section.StartsWith("[remote \"") && !section.StartsWith("[branch \""))
                    throw new ExportException("unsupported-git-input", "Git config section requires explicit support: " + section);
                continue;
            }
            var key = line.Split('=', 2)[0].Trim().ToLowerInvariant();
            var allowed = section == "[core]" ? new[] { "repositoryformatversion", "filemode", "bare", "logallrefupdates", "ignorecase", "precomposeunicode" }
                : section.StartsWith("[remote \"") ? ["url", "fetch"] : new[] { "remote", "merge" };
            if (!allowed.Contains(key) || line.EndsWith('\\'))
                throw new ExportException("unsupported-git-input", "Git config key requires explicit support: " + key);
        }
    }
}
