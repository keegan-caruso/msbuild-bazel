using System.Buffers;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Microsoft.Win32.SafeHandles;

namespace RulesMSBuild.Preparation;

internal static class FileTree
{
    private static FileStream OpenRegular(string path)
    {
        // Linux ARM64 uses a different O_NOFOLLOW value from Linux x86-64.
        var flags = OperatingSystem.IsMacOS() ? 0x104 : OperatingSystem.IsLinux() ? RuntimeInformation.ProcessArchitecture == Architecture.Arm64 ? 0x8800 : 0x20800 : throw new PlatformNotSupportedException();
        var fd = Open(path, flags);
        if (fd < 0) throw new IOException("Cannot open regular input: " + path);
        var handle = new SafeFileHandle((IntPtr)fd, true);
        var buffer = IntPtr.Zero;
        try
        {
            buffer = Marshal.AllocHGlobal(512);
            var status = OperatingSystem.IsMacOS() ? FStat(fd, buffer) : Statx(fd, "", 0x1000, 1, buffer);
            var mode = status == 0 ? (ushort)Marshal.ReadInt16(buffer, OperatingSystem.IsMacOS() ? 4 : 28) : 0;
            if ((mode & 0xf000) != 0x8000) throw new InvalidDataException("Input must be a regular file: " + path);
            return new FileStream(handle, FileAccess.Read);
        }
        catch { handle.Dispose(); throw; }
        finally { if (buffer != IntPtr.Zero) Marshal.FreeHGlobal(buffer); }
    }
    internal static byte[] ReadRegular(string path)
    {
        using var stream = OpenRegular(path); using var data = new MemoryStream(); stream.CopyTo(data); return data.ToArray();
    }
    internal static (long Length, string Digest) HashRegular(string path, IntegrityProfile? profile = null)
    {
        var started = profile is null ? default : IntegrityProfile.Begin();
        using var stream = OpenRegular(path); profile?.End("open", started);
        started = profile is null ? default : IntegrityProfile.Begin();
        using var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256); profile?.End("hash", started);
        var buffer = ArrayPool<byte>.Shared.Rent(64 * 1024);
        try
        {
            long length = 0;
            while (true)
            {
                started = profile is null ? default : IntegrityProfile.Begin();
                var count = stream.Read(buffer.AsSpan()); profile?.End("read", started);
                if (count == 0) break;
                length += count;
                started = profile is null ? default : IntegrityProfile.Begin();
                hash.AppendData(buffer.AsSpan(0, count)); profile?.End("hash", started);
            }
            started = profile is null ? default : IntegrityProfile.Begin();
            var digest = Convert.ToHexStringLower(hash.GetHashAndReset()); profile?.End("hash", started);
            return (length, digest);
        }
        finally { ArrayPool<byte>.Shared.Return(buffer); }
    }
    [DllImport("libc", EntryPoint = "open", SetLastError = true)]
    private static extern int Open(string path, int flags);
    [DllImport("libc", EntryPoint = "fstat", SetLastError = true)]
    private static extern int FStat(int fd, IntPtr buffer);
    [DllImport("libc", EntryPoint = "statx", SetLastError = true)]
    private static extern int Statx(int fd, string path, int flags, uint mask, IntPtr buffer);
    public static UnixFileMode Mode(string path)
    {
        if (OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Unix inputs required");
        return File.GetUnixFileMode(path);
    }
    public static void SetMode(string path, UnixFileMode mode)
    {
        if (OperatingSystem.IsWindows()) throw new PlatformNotSupportedException("Unix inputs required");
        File.SetUnixFileMode(path, mode);
    }
    public static IEnumerable<string> Files(string root) => Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories).Order(StringComparer.Ordinal);
    public static JsonObject Snapshot(string root, bool followLinks = false, IntegrityProfile? profile = null, bool deduplicateLinks = true)
    {
        var result = new JsonObject();
        // This cache lives for one scan only. Aliases retain their own manifest
        // records and metadata checks; later validation starts from fresh bytes.
        var contents = new Dictionary<string, (long Length, DateTime Written, int Mode, string Digest)>(StringComparer.Ordinal);
        var active = new HashSet<string>(StringComparer.Ordinal);
        void Visit(string path, string name)
        {
            FileSystemInfo info = Directory.Exists(path) ? new DirectoryInfo(path) : new FileInfo(path);
            if (info.LinkTarget is { } link)
            {
                if (!followLinks) throw new InvalidDataException("Linked input: " + path);
                result[name] = new JsonObject { ["kind"] = "link", ["target"] = link };
                Visit(Host.Real(path), name + "/@target");
                return;
            }
            var mode = (int)Mode(path);
            if (Directory.Exists(path))
            {
                if (!active.Add(path)) throw new InvalidDataException("Input link cycle");
                var children = Directory.GetFileSystemEntries(path).Order(StringComparer.Ordinal).ToArray();
                result[name] = new JsonObject { ["kind"] = "directory", ["mode"] = mode };
                foreach (var child in children) Visit(child, name == "." ? Path.GetFileName(child) : name + "/" + Path.GetFileName(child));
                if (!children.SequenceEqual(Directory.GetFileSystemEntries(path).Order(StringComparer.Ordinal))) throw new InvalidDataException("Input namespace changed");
                active.Remove(path);
            }
            else
            {
                var before = new FileInfo(path); var length = before.Length; var written = before.LastWriteTimeUtc;
                (long Length, string Digest) content;
                if (followLinks && deduplicateLinks && contents.TryGetValue(path, out var known))
                {
                    if (known.Length != length || known.Written != written || known.Mode != mode) throw new InvalidDataException("Input changed between aliases: " + path);
                    content = (known.Length, known.Digest);
                    if (profile is not null) { profile.ReusedFiles++; profile.ReusedBytes += content.Length; }
                }
                else content = HashRegular(path, profile);
                if (profile is not null) { profile.Files++; profile.ContentBytes += content.Length; }
                var after = new FileInfo(path);
                if (length != content.Length || length != after.Length || written != after.LastWriteTimeUtc || mode != (int)Mode(path)) throw new InvalidDataException("Input changed while reading: " + path);
                if (followLinks && deduplicateLinks) contents[path] = (content.Length, written, mode, content.Digest);
                var started = profile is null ? default : IntegrityProfile.Begin();
                result[name] = new JsonObject { ["kind"] = "file", ["mode"] = mode, ["size"] = content.Length, ["sha256"] = content.Digest };
                profile?.End("fileManifest", started);
            }
        }
        Visit(root, ".");
        return result;
    }
    // One instance belongs to one final validation pass. Every caller's original
    // expectation is checked, even when callers share the same physical input.
    internal sealed class Verification(Func<string, bool, JsonObject>? scan = null)
    {
        private readonly Dictionary<(string Root, bool FollowLinks), JsonObject> snapshots = new();
        public int Scans => snapshots.Count;
        public int Requests { get; private set; }
        public void Verify(string root, JsonNode expected, bool followLinks = false)
        {
            Requests++;
            var key = (root, followLinks);
            if (!snapshots.TryGetValue(key, out var actual)) snapshots[key] = actual = scan is null ? Snapshot(root, followLinks) : scan(root, followLinks);
            if (!JsonNode.DeepEquals(actual, expected))
            {
                var changed = actual.Select(p => p.Key).Union(expected.AsObject().Select(p => p.Key)).Where(k => !JsonNode.DeepEquals(actual[k], expected[k])).Take(5);
                throw new InvalidDataException("Leased inputs changed: " + root + ": " + string.Join(", ", changed));
            }
        }
    }
    public static void Verify(string root, JsonNode expected, bool followLinks = false) => new Verification().Verify(root, expected, followLinks);
    public static void Copy(string source, string target, bool preserveModes = true)
    {
        if (new DirectoryInfo(source).LinkTarget is not null) throw new InvalidDataException("Linked source directory");
        Directory.CreateDirectory(target);
        foreach (var path in Directory.GetFileSystemEntries(source))
        {
            FileSystemInfo info = Directory.Exists(path) ? new DirectoryInfo(path) : new FileInfo(path);
            if (info.LinkTarget is not null) throw new InvalidDataException("Linked input: " + path);
            var destination = Path.Combine(target, Path.GetFileName(path));
            if (Directory.Exists(path)) Copy(path, destination, preserveModes); else { Host.Copy(path, destination); SetMode(destination, Mode(path) | (preserveModes ? 0 : UnixFileMode.UserWrite)); }
        }
        SetMode(target, Mode(source) | (preserveModes ? 0 : UnixFileMode.UserWrite));
    }
    public static void Remove(string path)
    {
        if (!Directory.Exists(path)) return;
        if (new DirectoryInfo(path).LinkTarget is not null) throw new InvalidDataException("Refusing linked owned directory");
        SetMode(path, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        foreach (var child in Directory.GetDirectories(path)) Remove(child);
        Directory.Delete(path, true);
    }
    public static void Atomic(string path, JsonNode value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporary = path + "." + Guid.NewGuid().ToString("N");
        Json.Write(temporary, value); File.Move(temporary, path, true);
    }
    public static bool RestoreMetadata(string path) => path.Split('/').Contains("obj") && (Path.GetFileName(path) is "project.assets.json" or "project.nuget.cache" || new[] { ".nuget.g.props", ".nuget.g.targets", ".nuget.dgspec.json" }.Any(s => path.EndsWith(s, StringComparison.Ordinal)));
    public static JsonObject Portable(string root)
    {
        var result = Snapshot(root);
        foreach (var (path, entry) in result)
        {
            if (entry!.String("kind") != "file" || !RestoreMetadata(path)) continue;
            var data = File.ReadAllBytes(Path.Combine(root, path));
            var text = Encoding.UTF8.GetString(data).Replace(root, "${WORKSPACE}", StringComparison.Ordinal);
            if (Path.GetFileName(path) == "project.nuget.cache")
            {
                var receipt = JsonNode.Parse(text)!;
                if (receipt["success"]?.GetValue<bool>() != true) throw new InvalidDataException("Unsuccessful restore");
                if (receipt.AsObject().ContainsKey("dgSpecHash")) receipt["dgSpecHash"] = "$NORMALIZED";
                text = Json.Canonical(receipt);
            }
            data = Encoding.UTF8.GetBytes(text); entry!["size"] = data.Length; entry["sha256"] = Json.Sha(data);
        }
        return result;
    }
}
