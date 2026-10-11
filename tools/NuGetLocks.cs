namespace RulesMSBuild;

// Match NuGet's native precedence: existing project-specific lock, then default.
internal static class NuGetLocks
{
    private static string Named(string project) => Path.Combine(Path.GetDirectoryName(project)!,
        "packages." + Path.GetFileNameWithoutExtension(project).Replace(' ', '_') + ".lock.json");

    internal static string ForProject(string project) => File.Exists(Named(project)) ? Named(project) :
        Path.Combine(Path.GetDirectoryName(project)!, "packages.lock.json");

    internal static bool IsLockFile(string path) => Path.GetFileName(path) == "packages.lock.json" ||
        Path.GetFileName(path).StartsWith("packages.", StringComparison.Ordinal) && path.EndsWith(".lock.json", StringComparison.Ordinal);

    // Seed only in the owned updater copy. NuGet fills these blank native locks;
    // publication includes only projects reached by Restore, never unused seeds.
    internal static void SeedSharedDirectories(string root)
    {
        var projects = Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories)
            .Where(path => Path.GetExtension(path) is ".csproj" or ".ilproj" or ".proj");
        foreach (var group in projects.GroupBy(Path.GetDirectoryName).Where(group => group.Count() > 1))
        {
            var paths = group.Select(Named).Distinct(StringComparer.Ordinal).ToArray();
            foreach (var path in paths.Where(path => !File.Exists(path)))
            {
                File.WriteAllText(path, "");
            }
        }
    }
}
