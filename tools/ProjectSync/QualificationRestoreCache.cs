using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using RulesMSBuild.ProjectCache;

namespace RulesMSBuild.ProjectSync;

internal sealed record RestoreManifest(string Fingerprint, Dictionary<string, string> Files);
internal sealed record RestoreModes(Dictionary<string, int> Files, string[] Directories);

// Cache the exact offline Restore products at the sandbox's stable paths. File
// membership is always keyed; only explicitly reviewed Compile contents may vary.
internal sealed class QualificationRestoreCache : IDisposable
{
    private readonly string root;
    private readonly string fingerprint;
    private readonly string entry;
    private readonly SnapshotPayloads payloads;
    private readonly RemoteSnapshotStore? remote;
    private readonly Dictionary<string, string> authored;
    private string? pending;

    internal QualificationRestoreCache(string root, string sdk, IEnumerable<string> entries,
        Dictionary<string, string> properties, WorkspaceView view, GraphMappings mappings, QualificationOptions options)
    {
        using var profile = SyncProfile.Measure("restore-cache-inputs");
        this.root = root;
        authored = Files(root).ToDictionary(path => Path.GetRelativePath(root, path), Digest, StringComparer.Ordinal);
        var omitted = mappings.RestoreReuseInputs.ToHashSet(StringComparer.Ordinal);
        if (omitted.Any(path => !authored.ContainsKey(path)))
        {
            throw new InvalidDataException("restoreReuseInputs requires existing authored files");
        }
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
        Add("qualification-restore-v1");
        Add(mappings.CacheIdentity);
        Add(JsonSerializer.Serialize(entries));
        Add(JsonSerializer.Serialize(properties.OrderBy(pair => pair.Key, StringComparer.Ordinal)));
        Add(SnapshotPayloads.Digest(typeof(QualificationRestoreCache).Assembly.Location));
        Add(System.Runtime.InteropServices.RuntimeInformation.RuntimeIdentifier);
        Add(Math.Clamp(Environment.ProcessorCount, 1, 4).ToString(System.Globalization.CultureInfo.InvariantCulture));
        foreach (var path in new[] { "/etc/os-release", "/usr/bin/bwrap", "/bin/sh" })
        {
            Add(path);
            Add(Digest(path));
        }
        foreach (var path in Files(sdk).Order(StringComparer.Ordinal))
        {
            Add(Path.GetRelativePath(sdk, path));
            Add(Digest(path));
        }
        foreach (var package in view.GraphPackageDigests())
        {
            Add(package);
        }
        foreach (var (path, digest) in authored.OrderBy(pair => pair.Key, StringComparer.Ordinal))
        {
            Add(path);
            Add(omitted.Contains(path) ? Mode(Path.Combine(root, path)).ToString(System.Globalization.CultureInfo.InvariantCulture) : digest);
        }
        // Empty directories can affect Exists() and wildcard evaluation too.
        foreach (var path in Directory.EnumerateDirectories(root, "*", SearchOption.AllDirectories).Order(StringComparer.Ordinal))
        {
            Add(Path.GetRelativePath(root, path) + "/");
        }
        fingerprint = Convert.ToHexString(hash.GetHashAndReset()).ToLowerInvariant();
        var directory = Path.Combine(options.Directory, "restore");
        Directory.CreateDirectory(directory);
        if (new DirectoryInfo(directory).LinkTarget is not null)
        {
            throw new InvalidDataException("Restore cache directory must not be a symlink");
        }
        entry = Path.Combine(directory, fingerprint);
        payloads = new SnapshotPayloads(directory);
        remote = options.Url is null ? null : new RemoteSnapshotStore(new Uri(options.Url.TrimEnd('/') + "/"),
            bearerToken: Environment.GetEnvironmentVariable("RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN"), contentStore: payloads);
        return;

        void Add(string value)
        {
            var bytes = Encoding.UTF8.GetBytes(value);
            hash.AppendData(BitConverter.GetBytes(bytes.Length));
            hash.AppendData(bytes);
        }
    }

    internal bool Restore()
    {
        using var profile = SyncProfile.Measure("restore-cache-replay");
        var manifestPath = Path.Combine(entry, "manifest.json");
        if (!File.Exists(manifestPath) && remote is not null)
        {
            remote.FetchAsync(fingerprint, entry, CancellationToken.None).GetAwaiter().GetResult();
        }
        if (!File.Exists(manifestPath))
        {
            Console.Error.WriteLine("PROJECT_SYNC_RESTORE_CACHE miss");
            return false;
        }
        var manifest = JsonSerializer.Deserialize<RestoreManifest>(File.ReadAllText(manifestPath))
            ?? throw new InvalidDataException("Missing Restore cache manifest");
        if (manifest.Fingerprint != fingerprint || !manifest.Files.ContainsKey("modes.json"))
        {
            throw new InvalidDataException("Invalid Restore cache manifest");
        }
        foreach (var (path, digest) in manifest.Files)
        {
            var source = Resolve(entry, path);
            if (!File.Exists(source) || SnapshotPayloads.Digest(source) != digest)
            {
                throw new InvalidDataException("Corrupt Restore snapshot: " + path);
            }
        }
        var modes = JsonSerializer.Deserialize<RestoreModes>(File.ReadAllText(Resolve(entry, "modes.json")))
            ?? throw new InvalidDataException("Missing Restore cache modes");
        if (!modes.Files.Keys.Select(path => "outputs/" + path).ToHashSet(StringComparer.Ordinal)
            .SetEquals(manifest.Files.Keys.Where(path => path != "modes.json")))
        {
            throw new InvalidDataException("Invalid Restore cache file inventory");
        }
        foreach (var directory in modes.Directories)
        {
            Directory.CreateDirectory(Resolve(root, directory));
        }
        foreach (var (path, mode) in modes.Files)
        {
            if (authored.ContainsKey(path) || (mode & ~511) != 0)
            {
                throw new InvalidDataException("Restore snapshot overlaps authored inputs or has invalid modes: " + path);
            }
            var target = Resolve(root, path);
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            File.Copy(Resolve(entry, "outputs/" + path), target);
            if (!OperatingSystem.IsWindows())
            {
                File.SetUnixFileMode(target, (UnixFileMode)mode);
            }
        }
        Console.Error.WriteLine("PROJECT_SYNC_RESTORE_CACHE hit");
        return true;
    }

    internal void Capture()
    {
        using var profile = SyncProfile.Measure("restore-cache-capture");
        // A custom Restore may rewrite authored inputs. Preserve that behavior,
        // but never reuse it as an immutable prepared snapshot.
        if (authored.Any(pair => !File.Exists(Path.Combine(root, pair.Key)) || Digest(Path.Combine(root, pair.Key)) != pair.Value))
        {
            return;
        }
        pending = entry + ".pending-" + Guid.NewGuid().ToString("N");
        Directory.CreateDirectory(pending);
        var files = new Dictionary<string, string>(StringComparer.Ordinal);
        var modes = new Dictionary<string, int>(StringComparer.Ordinal);
        foreach (var source in Files(root))
        {
            var path = Path.GetRelativePath(root, source);
            if (authored.ContainsKey(path) || path.StartsWith(".cli/", StringComparison.Ordinal) || path.StartsWith(".package-source/", StringComparison.Ordinal) || path == ".graph.nuget.config")
            {
                continue;
            }
            var digest = SnapshotPayloads.Digest(source);
            files["outputs/" + path] = digest;
            modes[path] = Mode(source);
            payloads.Store(source, digest, Path.Combine(pending, "outputs", path));
        }
        var metadata = Path.Combine(pending, "modes.json");
        File.WriteAllText(metadata, JsonSerializer.Serialize(new RestoreModes(modes, Directory.EnumerateDirectories(root, "*", SearchOption.AllDirectories)
            .Select(path => Path.GetRelativePath(root, path)).Where(path => path != ".cli" && !path.StartsWith(".cli/", StringComparison.Ordinal) && path != ".package-source" && !path.StartsWith(".package-source/", StringComparison.Ordinal)).Order(StringComparer.Ordinal).ToArray())));
        files["modes.json"] = SnapshotPayloads.Digest(metadata);
        File.WriteAllText(Path.Combine(pending, "manifest.json"), JsonSerializer.Serialize(new RestoreManifest(fingerprint, files)));
    }

    internal void Save()
    {
        if (pending is null)
        {
            return;
        }
        using var profile = SyncProfile.Measure("restore-cache-save");
        // Remote publication verifies any pre-existing action manifest as well.
        remote?.PublishAsync(fingerprint, pending, CancellationToken.None).GetAwaiter().GetResult();
        if (!Directory.Exists(entry))
        {
            try
            {
                Directory.Move(pending, entry);
            }
            catch (IOException) when (Directory.Exists(entry))
            {
                // Another successful invocation already published this key.
            }
        }
    }

    private static IEnumerable<string> Files(string directory)
    {
        foreach (var path in Directory.EnumerateFileSystemEntries(directory))
        {
            if (new FileInfo(path).LinkTarget is not null)
            {
                throw new InvalidDataException("Restore cache requires regular files and directories: " + path);
            }
            if (Directory.Exists(path))
            {
                foreach (var file in Files(path))
                {
                    yield return file;
                }
            }
            else
            {
                yield return path;
            }
        }
    }

    private static string Resolve(string directory, string path)
    {
        var target = Path.Combine(directory, WorkspaceView.Safe(path));
        for (var current = target; current.Length >= directory.Length; current = Path.GetDirectoryName(current)!)
        {
            if (new FileInfo(current).LinkTarget is not null)
            {
                throw new InvalidDataException("Restore cache symlink: " + current);
            }
            if (current == directory)
            {
                break;
            }
        }
        return target;
    }
    private static int Mode(string path) => OperatingSystem.IsWindows() ? 0 : (int)File.GetUnixFileMode(path) & 511;
    private static string Digest(string path) => SnapshotPayloads.Digest(path) + ":" + Mode(path).ToString(System.Globalization.CultureInfo.InvariantCulture);

    public void Dispose()
    {
        remote?.Dispose();
        if (pending is not null && Directory.Exists(pending))
        {
            Directory.Delete(pending, true);
        }
    }
}
