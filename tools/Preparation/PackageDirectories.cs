using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

// Tree artifacts are expanded only inside actions that actually execute.
internal static class PackageDirectories
{
    public static void Stage(JsonNode request, string workspace)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var row in request["packageDirectories"] as JsonArray ?? [])
        {
            var package = Host.Safe(row!.String("package"));
            if (package.Split('/').Length != 2 || package != package.ToLowerInvariant() || !seen.Add(package)) throw new InvalidDataException("Invalid or duplicate package directory identity");
            var source = row.String("source");
            foreach (var file in FileTree.Files(source))
            {
                var relative = Host.Safe(Path.GetRelativePath(source, file));
                var target = Path.Combine(workspace, ".nuget/packages", package, relative);
                if (File.Exists(target)) throw new InvalidDataException("Package directory overlaps a declared input: " + package + "/" + relative);
                Host.Copy(Host.Real(file), target);
                FileTree.SetMode(target, FileTree.Mode(target) | UnixFileMode.UserWrite);
            }
        }
    }
}
