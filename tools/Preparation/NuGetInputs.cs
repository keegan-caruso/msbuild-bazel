using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace RulesMSBuild.Preparation;

internal static class NuGetInputs
{
    private static JsonObject Locked(string source, string cache, JsonObject before, bool copyPackages)
    {
        var locked = new JsonObject();
        var local = Path.Combine(source, ".nuget/packages");
        foreach (var (name, item) in before)
        {
            if (item!.String("kind") != "file" || Path.GetFileName(name) != "project.assets.json" || !name.Split('/').Contains("obj")) continue;
            var assets = Json.Read(Path.Combine(source, name));
            var folders = assets["packageFolders"]!.AsObject().Select(p => Host.Real(p.Key)).ToHashSet(StringComparer.Ordinal);
            if (folders.Any(p => p != local && p != cache) || folders.Count > 1) throw new InvalidDataException("Restore uses a different or multiple NuGet caches");
            if (copyPackages && (!folders.Contains(cache) || cache == local)) continue;
            foreach (var library in assets["libraries"]!.AsObject().Select(p => p.Value!))
                if (library.String("type") == "package")
                {
                    var path = Host.Safe(library.String("path"));
                    if (path.Split('/').Length != 2) throw new InvalidDataException("Invalid package path");
                    var hash = copyPackages ? library["sha512"]?.GetValue<string>() ?? "" : library.String("sha512");
                    if (locked[path] is { } previous && previous.GetValue<string>() != hash) throw new InvalidDataException("Conflicting NuGet archive hashes");
                    locked[path] = hash;
                }
        }
        return locked;
    }
    public static JsonObject Describe(string source, string cache, JsonObject before)
    {
        var locked = Locked(source, cache, before, false);
        return new JsonObject { ["staged"] = false, ["packages"] = locked.Count, ["bytes"] = 0, ["copied"] = false, ["locked"] = locked };
    }
    public static JsonObject Stage(string source, string destination, string cache, bool copyPackages = true)
    {
        foreach (var other in new[] { source, cache })
            if (Host.Within(destination, other) || Host.Within(other, destination)) throw new InvalidDataException("NuGet paths must be disjoint");
        if (Host.Real(destination) != Path.GetFullPath(destination)) throw new InvalidDataException("Linked NuGet destination");
        var before = FileTree.Snapshot(source); var locked = Locked(source, cache, before, copyPackages);
        var packages = locked.Select(pair => pair.Key).ToHashSet(StringComparer.Ordinal);
        FileTree.Remove(destination);
        if (copyPackages) FileTree.Copy(source, destination);
        else
        {
            Directory.CreateDirectory(destination);
            foreach (var (name, item) in before)
                if (!name.StartsWith(".nuget/packages/", StringComparison.Ordinal) && item!.String("kind") == "file") Host.Copy(Path.Combine(source, name), Path.Combine(destination, name));
        }
        var packageRoot = Path.Combine(destination, ".nuget/packages"); Directory.CreateDirectory(packageRoot);
        long size = 0;
        foreach (var package in (copyPackages ? packages : []).Order(StringComparer.Ordinal))
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
        return new JsonObject { ["staged"] = true, ["packages"] = packages.Count, ["bytes"] = size, ["copied"] = copyPackages, ["locked"] = locked };
    }
}
