using System.Text.Json;
using Microsoft.Build.Execution;

// Keep SDK-selected package files distinct from project outputs when composing
// runfiles: the application may resolve a newer version than its dependencies.
internal static class RuntimePackages
{
    internal const string Manifest = ".rules-msbuild-packages.json";
    internal const string FilesManifest = ".rules-msbuild-package-files.json";
    internal sealed record PackageFile(string Id, string Version, string Path);
    internal static void Export(Session session, ProjectInstance project)
    {
        var files = new Dictionary<string, string>(StringComparer.Ordinal);
        var sources = new Dictionary<string, PackageFile>(StringComparer.Ordinal);
        var output = Path.Combine(session.State, "out");
        foreach (var item in project.GetItems("ReferenceCopyLocalPaths"))
        {
            var id = item.GetMetadataValue("NuGetPackageId");
            if (id.Length == 0)
            {
                continue;
            }

            var path = Program.Safe((item.GetMetadataValue("DestinationSubDirectory") + Path.GetFileName(item.EvaluatedInclude)).Replace('\\', '/'));
            var destination = Path.Combine(output, path);
            // Only classify a file actually copied from the package by the SDK.
            if (!File.Exists(destination))
            {
                continue;
            }

            if (!File.ReadAllBytes(destination).AsSpan().SequenceEqual(File.ReadAllBytes(item.EvaluatedInclude)))
            {
                throw new InvalidDataException("Package runtime output was replaced: " + path);
            }

            if (files.TryGetValue(path, out var previous) && !previous.Equals(id, StringComparison.OrdinalIgnoreCase))
            {
                throw new InvalidDataException("Conflicting package runtime destination: " + path);
            }

            files[path] = id;
            var package = session.Request.Packages.Single(p => p.Id.Equals(id, StringComparison.OrdinalIgnoreCase));
            // Request directories may be execroot-relative; the compiler runs in its workspace.
            var packageRoot = Path.Combine(session.Workspace, ".nuget", "packages", Program.Safe(package.Id.ToLowerInvariant()), Program.Safe(package.Version));
            var relative = Program.Safe(Path.GetRelativePath(Program.Real(packageRoot), Program.Real(item.EvaluatedInclude)).Replace('\\', '/'));
            sources[path] = new(package.Id, package.Version, relative);
        }
        var manifest = Path.Combine(output, Manifest);
        if (File.Exists(manifest))
        {
            throw new InvalidDataException("Reserved runtime output: " + Manifest);
        }

        File.WriteAllText(manifest, JsonSerializer.Serialize(files, Program.Json));
        var sourceManifest = Path.Combine(output, FilesManifest);
        if (File.Exists(sourceManifest))
        {
            throw new InvalidDataException("Reserved runtime output: " + FilesManifest);
        }

        File.WriteAllText(sourceManifest, JsonSerializer.Serialize(sources, Program.Json));
    }
    internal static Dictionary<string, string> Read(string directory) => JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(Path.Combine(directory, Manifest)), Program.Json)!;
    internal static Dictionary<string, PackageFile> ReadFiles(string directory) => JsonSerializer.Deserialize<Dictionary<string, PackageFile>>(File.ReadAllText(Path.Combine(directory, FilesManifest)), Program.Json)!;
    internal static IEnumerable<Input> Files(string directory, PackageInput[] packages)
    {
        foreach (var file in Directory.GetFiles(directory, "*", SearchOption.AllDirectories))
        {
            var relative = Path.GetRelativePath(directory, file);
            if (relative is not Manifest and not FilesManifest)
            {
                yield return new(file, relative);
            }
        }
        foreach (var (destination, source) in ReadFiles(directory))
        {
            var package = packages.FirstOrDefault(p => p.Id.Equals(source.Id, StringComparison.OrdinalIgnoreCase) && p.Version.Equals(source.Version, StringComparison.OrdinalIgnoreCase))
                ?? throw new InvalidDataException("Undeclared runtime package: " + source.Id + "/" + source.Version);
            yield return new(Path.Combine(package.Directory, Program.Safe(source.Path)), Program.Safe(destination));
        }
    }
}
