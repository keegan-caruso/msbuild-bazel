using System.Security.Cryptography;
using System.Text.Json;

namespace RulesMSBuild.ProjectSync;

internal static class NuGetConfigs
{
    internal static void RequireRoot(string workspace)
    {
        if (Directory.EnumerateFiles(workspace).Count(IsConfig) != 1)
        {
            throw new InvalidDataException("NuGet update requires one unambiguous authored root NuGet.Config");
        }
    }

    internal static SortedDictionary<string, string> Capture(string workspace, string source, string home, Dictionary<string, string> originals)
    {
        var configs = new SortedDictionary<string, string>(StringComparer.Ordinal);
        foreach (var assets in Directory.GetFiles(workspace, "project.assets.json", SearchOption.AllDirectories))
        {
            using var document = JsonDocument.Parse(File.ReadAllText(assets));
            foreach (var item in document.RootElement.GetProperty("project").GetProperty("restore").GetProperty("configFilePaths").EnumerateArray())
            {
                var path = Path.GetFullPath(item.GetString()!);
                if (path.StartsWith(home + Path.DirectorySeparatorChar, StringComparison.Ordinal))
                {
                    // Only NuGet's defaults created inside this update's private home.
                    continue;
                }
                if (!path.StartsWith(workspace + Path.DirectorySeparatorChar, StringComparison.Ordinal))
                {
                    throw new InvalidDataException("NuGet Restore read configuration outside the workspace; existing locks were left unchanged: " + path);
                }
                var relative = WorkspaceView.Safe(Path.GetRelativePath(workspace, path).Replace('\\', '/'));
                if (!originals.TryGetValue(Path.Combine(source, relative), out var digest))
                {
                    throw new InvalidDataException("NuGet Restore read an unauthored config; existing locks were left unchanged: " + relative);
                }
                using var stream = File.OpenRead(path);
                if (Convert.ToHexString(SHA256.HashData(stream)) != digest)
                {
                    throw new InvalidDataException("NuGet config changed in the update workspace; existing locks were left unchanged: " + relative);
                }
                configs[relative] = digest;
            }
        }
        if (!configs.Keys.Any(path => !path.Contains('/') && IsConfig(path)))
        {
            throw new InvalidDataException("NuGet Restore did not use the authored root config; existing locks were left unchanged");
        }
        return configs;
    }

    private static bool IsConfig(string path) => Path.GetFileName(path).Equals("NuGet.Config", StringComparison.OrdinalIgnoreCase);
}
