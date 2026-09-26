using System.Text.Json;
using System.Text.Json.Serialization;

namespace RulesMSBuild.ProjectSync;

internal sealed record SyncInput(string Path, string Label, string Runfile);
internal sealed record SyncPackage(string Id, string Version, string Runfile);
internal sealed record SyncBinding(string Label, string Property, string[] Runfiles, string Entry);
internal sealed record SyncPackageLock(string Label, string[] Packages);
internal sealed record SyncInputs(SyncInput[] Inputs, SyncPackage[] Packages, string? PackageLock, SyncBinding[]? Bindings = null, SyncPackageLock[]? PackageLocks = null);

// A local evaluation view only. No MSBuild targets execute here; normal builds
// consume producer labels and the same logical paths, never this temporary root.
internal sealed class WorkspaceView : IDisposable
{
    private readonly string? temporary;
    private readonly Dictionary<string, string> packageSources = new(StringComparer.Ordinal);
    private readonly Dictionary<string, (string Label, HashSet<string> Packages)> packageLocks = new(StringComparer.Ordinal);
    private readonly HashSet<string> visiblePackages = new(StringComparer.Ordinal);
    internal string? DefaultPackageLock
    {
        get;
    }
    private readonly Dictionary<string, (string Property, string Value)> bindings = new(StringComparer.Ordinal);
    internal string Root
    {
        get;
    }
    internal string? PackageLock
    {
        get; private set;
    }
    internal Dictionary<string, string> Labels { get; } = new(StringComparer.Ordinal);

    private WorkspaceView(string root, string? temporary, string? packageLock)
    {
        Root = root;
        this.temporary = temporary;
        DefaultPackageLock = packageLock;
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
                if (!Directory.Exists(source) || !view.packageSources.TryAdd(identity, source))
                {
                    throw new InvalidDataException("Missing or conflicting SDK package: " + identity);
                }
            }
            foreach (var packageLock in inputs.PackageLocks ?? (inputs.PackageLock is null ? [] : new[] { new SyncPackageLock(inputs.PackageLock, view.packageSources.Keys.ToArray()) }))
            {
                var members = packageLock.Packages.Select(p => Safe(p.ToLowerInvariant())).ToHashSet(StringComparer.Ordinal);
                if (members.Any(p => !view.packageSources.ContainsKey(p)) || !view.packageLocks.TryAdd(LabelKey(packageLock.Label), (packageLock.Label, members)))
                {
                    throw new InvalidDataException("Missing or conflicting sync package lock: " + packageLock.Label);
                }
            }
            view.SelectPackageLock(inputs.PackageLock);
            // A missing SDK must not fall back to a user's feeds/cache.
            var configName = Directory.EnumerateFiles(root).Select(Path.GetFileName).FirstOrDefault(name => name!.Equals("NuGet.Config", StringComparison.OrdinalIgnoreCase)) ?? "NuGet.Config";
            var config = Path.Combine(temporary, configName);
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

    internal void SelectPackageLock(string? label)
    {
        var wanted = new HashSet<string>(StringComparer.Ordinal);
        string? selected = null;
        if (label is not null)
        {
            if (!packageLocks.TryGetValue(LabelKey(label), out var packageLock))
            {
                throw new InvalidDataException("Project packageLock must also be a declared sync package lock: " + label);
            }
            wanted = packageLock.Packages;
            selected = packageLock.Label;
        }
        var packageRoot = Path.Combine(Root, ".nuget", "packages");
        foreach (var identity in visiblePackages.Except(wanted, StringComparer.Ordinal).ToArray())
        {
            var path = Path.Combine(packageRoot, identity);
            Directory.Delete(path);
            var parent = Path.GetDirectoryName(path)!;
            if (!Directory.EnumerateFileSystemEntries(parent).Any())
            {
                Directory.Delete(parent);
            }
            visiblePackages.Remove(identity);
        }
        foreach (var identity in wanted.Except(visiblePackages, StringComparer.Ordinal))
        {
            var path = Path.Combine(packageRoot, identity);
            Directory.CreateDirectory(Path.GetDirectoryName(path)!);
            Directory.CreateSymbolicLink(path, packageSources[identity]);
            visiblePackages.Add(identity);
        }
        PackageLock = selected;
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
