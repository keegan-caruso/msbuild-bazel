using System.Text.Json;

namespace RulesMSBuild.ProjectSync;

internal sealed record SyncStageFile(string Path, string File, bool Tree = false);
internal sealed record SyncStage(SyncStageFile[] Sources, SyncStageFile[] Runfiles);

// Bazel owns cache identity. This tool stages only declared artifacts and publishes
// the resulting declarations; it does not maintain a second qualification cache.
internal static class PreparedSync
{
    internal static void Stage(string manifest, string destination)
    {
        using var profile = SyncProfile.Measure("declared-source-staging");
        var data = JsonSerializer.Deserialize<SyncStage>(File.ReadAllText(manifest), new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true,
            UnmappedMemberHandling = System.Text.Json.Serialization.JsonUnmappedMemberHandling.Disallow
        }) ?? throw new InvalidDataException("Empty sync staging manifest");
        Copy(data.Sources, "workspace", false);
        Copy(data.Runfiles, "runfiles", true);

        void Copy(SyncStageFile[] files, string directory, bool links)
        {
            var root = Path.Combine(destination, directory);
            Directory.CreateDirectory(root);
            var paths = files.Select(file => WorkspaceView.Safe(file.Path)).ToHashSet(StringComparer.Ordinal);
            if (paths.Count != files.Length)
            {
                throw new InvalidDataException("Overlapping sync staging paths");
            }
            foreach (var path in paths)
            {
                for (var parent = Path.GetDirectoryName(path); !string.IsNullOrEmpty(parent); parent = Path.GetDirectoryName(parent))
                {
                    if (paths.Contains(parent.Replace('\\', '/')))
                    {
                        throw new InvalidDataException("Overlapping sync staging paths");
                    }
                }
            }
            foreach (var file in files)
            {
                var source = Path.GetFullPath(file.File);
                var target = Path.Combine(root, file.Path);
                Directory.CreateDirectory(Path.GetDirectoryName(target)!);
                if (links && file.Tree && Directory.Exists(source))
                {
                    MaterializeTree(file, source, target);
                }
                else if (links && !file.Tree && Directory.Exists(source))
                {
                    Directory.CreateSymbolicLink(target, source);
                }
                else if (links && !file.Tree && File.Exists(source))
                {
                    File.CreateSymbolicLink(target, source);
                }
                else if (!links && File.Exists(source) && !Directory.Exists(source))
                {
                    File.Copy(source, target);
                }
                else
                {
                    throw new InvalidDataException("Missing or non-file sync source: " + file.Path);
                }
            }
        }
    }

    private static void MaterializeTree(SyncStageFile artifact, string source, string target)
    {
        string? projection = null;
        Copy(source, target);

        void Copy(string directory, string output)
        {
            Directory.CreateDirectory(output);
            foreach (var entry in Directory.EnumerateFileSystemEntries(directory))
            {
                var destination = Path.Combine(output, Path.GetFileName(entry));
                if (Directory.Exists(entry))
                {
                    if (new DirectoryInfo(entry).LinkTarget is not null)
                    {
                        throw new InvalidDataException("Producer tree directory symlinks are unsupported: " + entry);
                    }
                    Copy(entry, destination);
                    continue;
                }
                var link = new FileInfo(entry).LinkTarget;
                if (link is not null)
                {
                    // A sandbox projection points one hop to the same declared
                    // artifact path in the real execroot. Authored links do not.
                    var original = Path.GetFullPath(link, directory);
                    var relative = Path.GetRelativePath(source, entry);
                    var suffix = Path.DirectorySeparatorChar + WorkspaceView.Safe(artifact.File).Replace('/', Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar + relative;
                    if (!original.EndsWith(suffix, StringComparison.Ordinal) || new FileInfo(original).LinkTarget is not null)
                    {
                        throw new InvalidDataException("Producer tree symlinks are unsupported: " + entry);
                    }
                    var root = original[..^(relative.Length + 1)];
                    if (projection is not null && projection != root)
                    {
                        throw new InvalidDataException("Inconsistent producer tree projection: " + entry);
                    }
                    projection = root;
                    for (var parent = Path.GetDirectoryName(original); parent is not null && parent.Length >= root.Length; parent = Path.GetDirectoryName(parent))
                    {
                        if (new DirectoryInfo(parent).LinkTarget is not null)
                        {
                            throw new InvalidDataException("Producer tree directory symlinks are unsupported: " + entry);
                        }
                    }
                }
                File.Copy(entry, destination);
            }
        }
    }

    internal static void Publish(string[] args)
    {
        if (args.Length is < 2 or > 3 || args.Length == 3 && args[2] != "--check")
        {
            throw new ArgumentException("Prepared sync accepts only --check; change configuration in the Bazel target");
        }
        GraphGenerator.Publish(args[1], args.Length == 3,
            File.ReadAllText(Path.Combine(args[0], "graph.generated.json")),
            File.ReadAllText(Path.Combine(args[0], "graph.generated.bzl")));
    }
}
