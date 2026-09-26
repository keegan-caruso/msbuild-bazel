using System.Text.Json;
using System.Text.Json.Serialization;

namespace RulesMSBuild.ProjectSync;

internal sealed record SyncInput(string Path, string Label, string Runfile);
internal sealed record SyncPackage(string Id, string Version, string Runfile);
internal sealed record SyncBinding(string Label, string Property, string[] Runfiles, string Entry);
internal sealed record SyncInputs(SyncInput[] Inputs, SyncPackage[] Packages, string? PackageLock, SyncBinding[]? Bindings = null);

// A local evaluation view only. No MSBuild targets execute here; normal builds
// consume producer labels and the same logical paths, never this temporary root.
internal sealed class WorkspaceView : IDisposable
{
    private readonly string? temporary;
    private readonly Dictionary<string, (string Property, string Value)> bindings = new(StringComparer.Ordinal);
    internal string Root
    {
        get;
    }
    internal string? PackageLock
    {
        get;
    }
    internal Dictionary<string, string> Labels { get; } = new(StringComparer.Ordinal);

    private WorkspaceView(string root, string? temporary, string? packageLock)
    {
        Root = root;
        this.temporary = temporary;
        PackageLock = packageLock;
    }

    internal static string Safe(string path)
    {
        if (Path.IsPathRooted(path) || path.Contains('\\') || path.Split('/').Any(p => p is "" or "." or ".."))
        {
            throw new InvalidDataException("Expected a safe relative input path: " + path);
        }
        return path;
    }

    internal static WorkspaceView Create(string root, string? manifest, string? runfiles)
    {
        if (manifest is null)
        {
            return new WorkspaceView(root, null, null);
        }
        if (runfiles is null)
        {
            throw new InvalidDataException("--inputs requires --runfiles");
        }
        var inputs = JsonSerializer.Deserialize<SyncInputs>(File.ReadAllText(manifest), new JsonSerializerOptions { PropertyNameCaseInsensitive = true, UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow }) ?? throw new InvalidDataException("Empty sync input manifest");
        var temporary = Directory.CreateTempSubdirectory("msbuild-sync-").FullName;
        var view = new WorkspaceView(temporary, temporary, inputs.PackageLock);
        try
        {
            CopySources(root, temporary);
            foreach (var input in inputs.Inputs)
            {
                var path = Safe(input.Path);
                if (path.Split('/').Any(p => p is ".git" or ".nuget") || !view.Labels.TryAdd(path, input.Label))
                {
                    throw new InvalidDataException("Duplicate or reserved sync input: " + path);
                }
                var source = Path.Combine(runfiles, Safe(input.Runfile));
                var destination = Path.Combine(temporary, path);
                if (!File.Exists(source) || Path.Exists(destination))
                {
                    throw new InvalidDataException("Missing producer or colliding source input: " + path);
                }
                Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
                File.CreateSymbolicLink(destination, source);
            }
            foreach (var binding in inputs.Bindings ?? [])
            {
                var paths = binding.Runfiles.Select(path => Path.Combine(runfiles, Safe(path), Safe(binding.Entry))).Where(File.Exists).ToArray();
                if (paths.Length != 1 || !view.bindings.TryAdd(LabelKey(binding.Label), (binding.Property, paths[0])))
                {
                    throw new InvalidDataException("Ambiguous or missing evaluation tool: " + binding.Label);
                }
            }
            var packageRoot = Path.Combine(temporary, ".nuget", "packages");
            Directory.CreateDirectory(packageRoot);
            foreach (var package in inputs.Packages)
            {
                var identity = Safe(package.Id.ToLowerInvariant() + "/" + package.Version.ToLowerInvariant());
                var source = Path.Combine(runfiles, Safe(package.Runfile));
                var destination = Path.Combine(packageRoot, identity);
                if (!Directory.Exists(source) || Path.Exists(destination))
                {
                    throw new InvalidDataException("Missing or conflicting SDK package: " + identity);
                }
                Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
                Directory.CreateSymbolicLink(destination, source);
            }
            // A missing SDK must not fall back to a user's feeds/cache.
            var config = Path.Combine(temporary, "NuGet.Config");
            File.Delete(config);
            File.WriteAllText(config, "<configuration><packageSources><clear/></packageSources><fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>");
            Environment.SetEnvironmentVariable("NUGET_PACKAGES", packageRoot);
            Environment.SetEnvironmentVariable("NUGET_HTTP_CACHE_PATH", Path.Combine(temporary, ".http"));
            return view;
        }
        catch
        {
            view.Dispose();
            throw;
        }
    }

    private static void CopySources(string source, string destination)
    {
        foreach (var entry in Directory.EnumerateFileSystemEntries(source))
        {
            var name = Path.GetFileName(entry);
            if (name is ".git" or ".tools" or ".cache" or ".nuget" or "bin" or "obj" || name.StartsWith("bazel-", StringComparison.Ordinal) || name.Equals("NuGet.Config", StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            var target = Path.Combine(destination, name);
            if (Directory.Exists(entry))
            {
                if ((File.GetAttributes(entry) & FileAttributes.ReparsePoint) != 0)
                {
                    throw new InvalidDataException("Directory symlink requires explicit sync inputs: " + entry);
                }
                Directory.CreateDirectory(target);
                CopySources(entry, target);
            }
            else
            {
                File.CreateSymbolicLink(target, entry);
            }
        }
    }

    private static string LabelKey(string label) => label.StartsWith(':') ? "@@//" + label : label.StartsWith("//", StringComparison.Ordinal) ? "@@" + label : label;
    internal IEnumerable<KeyValuePair<string, string>> ToolProperties(IEnumerable<string> labels)
    {
        foreach (var label in labels)
        {
            if (!bindings.TryGetValue(LabelKey(label), out var binding))
            {
                throw new InvalidDataException("Task binding must also be a sync bindings input: " + label);
            }
            yield return new KeyValuePair<string, string>(binding.Property, binding.Value);
        }
    }

    internal bool IsPackage(string path) => path.StartsWith(Path.Combine(Root, ".nuget", "packages") + Path.DirectorySeparatorChar, StringComparison.Ordinal);
    internal Dictionary<string, string> Bindings(IEnumerable<string> paths) => paths.Distinct(StringComparer.Ordinal).Where(Labels.ContainsKey).ToDictionary(path => Labels[path], path => path, StringComparer.Ordinal);
    public void Dispose()
    {
        if (temporary is not null)
        {
            Directory.Delete(temporary, true);
        }
    }
}
