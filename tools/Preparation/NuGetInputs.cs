using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace RulesMSBuild.Preparation;

internal static class NuGetInputs
{
    public static JsonObject Stage(string source, string destination, string cache)
    {
        foreach (var other in new[] { source, cache })
            if (Host.Within(destination, other) || Host.Within(other, destination)) throw new InvalidDataException("NuGet paths must be disjoint");
        if (Host.Real(destination) != Path.GetFullPath(destination)) throw new InvalidDataException("Linked NuGet destination");
        var before = FileTree.Snapshot(source); var packages = new HashSet<string>(StringComparer.Ordinal);
        var local = Path.Combine(source, ".nuget/packages");
        foreach (var (name, item) in before)
        {
            if (item!.String("kind") != "file" || Path.GetFileName(name) != "project.assets.json" || !name.Split('/').Contains("obj")) continue;
            var assets = Json.Read(Path.Combine(source, name));
            var folders = assets["packageFolders"]!.AsObject().Select(p => Host.Real(p.Key)).ToHashSet(StringComparer.Ordinal);
            if (folders.Any(p => p != local && p != cache) || folders.Count > 1) throw new InvalidDataException("Restore uses a different or multiple NuGet caches");
            if (!folders.Contains(cache) || cache == local) continue;
            foreach (var library in assets["libraries"]!.AsObject().Select(p => p.Value!))
                if (library.String("type") == "package")
                {
                    var path = Host.Safe(library.String("path"));
                    if (path.Split('/').Length != 2) throw new InvalidDataException("Invalid package path");
                    packages.Add(path);
                }
        }
        FileTree.Remove(destination); FileTree.Copy(source, destination);
        var packageRoot = Path.Combine(destination, ".nuget/packages"); Directory.CreateDirectory(packageRoot);
        long size = 0;
        foreach (var package in packages.Order(StringComparer.Ordinal))
        {
            var original = Path.Combine(cache, package); var target = Path.Combine(packageRoot, package);
            if (!Directory.Exists(original)) throw new InvalidDataException("Missing NuGet package; run restore: " + package);
            if (Host.Real(original) != original) throw new InvalidDataException("Linked NuGet package");
            var expected = FileTree.Snapshot(original);
            FileTree.Remove(target); FileTree.Copy(original, target); FileTree.Verify(original, expected); FileTree.Verify(target, expected);
            size += expected.Sum(p => p.Value?["size"]?.GetValue<long>() ?? 0);
        }
        FileTree.Verify(source, before);
        var replacements = new Dictionary<string, string> { [source] = destination };
        if (cache != source) replacements[cache] = packageRoot;
        var expression = new Regex("(" + string.Join("|", replacements.Keys.OrderByDescending(k => k.Length).Select(Regex.Escape)) + ")(?=/|[\"'<\\s]|$)");
        foreach (var path in FileTree.Files(destination).Where(FileTree.RestoreMetadata))
        {
            var text = Encoding.UTF8.GetString(File.ReadAllBytes(path));
            File.WriteAllBytes(path, Encoding.UTF8.GetBytes(expression.Replace(text, m => replacements[m.Value])));
        }
        foreach (var path in Directory.GetFileSystemEntries(destination, "*", SearchOption.AllDirectories).Append(destination)) File.SetLastWriteTimeUtc(path, new DateTime(2000, 1, 1, 0, 0, 0, DateTimeKind.Utc));
        return new JsonObject { ["staged"] = true, ["packages"] = packages.Count, ["bytes"] = size };
    }
}
