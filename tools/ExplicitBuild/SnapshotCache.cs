using System.Runtime.InteropServices;
using System.Security.Cryptography;

// Broker-owned store. Neither its path nor its directory is mounted in the child.
internal sealed class SnapshotCache(string root, bool reuse = true, long limit = 1024L * 1024 * 1024)
{
    private sealed record Entry(string Path, long Size, LinkedListNode<string> Position);
    private readonly Dictionary<string, Entry> entries = new(StringComparer.Ordinal);
    private readonly LinkedList<string> lru = new();
    private long residentBytes;
    internal long VerifiedBytes { get; private set; }
    internal long ReusedBytes { get; private set; }
    internal int ReusedFiles { get; private set; }

    [DllImport("libc", EntryPoint = "link", SetLastError = true)]
    private static extern int Link(string source, string destination);

    internal void Begin() { VerifiedBytes = 0; ReusedBytes = 0; ReusedFiles = 0; }

    internal void Stage(string source, string target, string digest)
    {
        if (!OperatingSystem.IsLinux()) throw new PlatformNotSupportedException();
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        const UnixFileMode execute = UnixFileMode.UserExecute | UnixFileMode.GroupExecute | UnixFileMode.OtherExecute;
        var executable = (File.GetUnixFileMode(source) & execute) != 0;
        var key = digest + (executable ? "-x" : "-r");
        if (reuse && entries.TryGetValue(key, out var entry))
        {
            if (Link(entry.Path, target) != 0) throw new IOException("Cannot link verified worker input", new System.ComponentModel.Win32Exception(Marshal.GetLastPInvokeError()));
            ReusedBytes += entry.Size; ReusedFiles++;
            lru.Remove(entry.Position); lru.AddLast(entry.Position);
            return;
        }
        File.Copy(source, target);
        if (Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(target))) != digest) { File.Delete(target); throw new InvalidDataException("Worker input digest mismatch: " + source); }
        var size = new FileInfo(target).Length;
        VerifiedBytes += size;
        File.SetUnixFileMode(target, UnixFileMode.UserRead | UnixFileMode.GroupRead | UnixFileMode.OtherRead | (executable ? execute : 0));
        if (reuse && size <= limit)
        {
            Directory.CreateDirectory(root);
            var cached = Path.Combine(root, key);
            if (Link(target, cached) != 0) throw new IOException("Cannot retain verified worker input", new System.ComponentModel.Win32Exception(Marshal.GetLastPInvokeError()));
            entries.Add(key, new(cached, size, lru.AddLast(key))); residentBytes += size;
            while (residentBytes > limit || entries.Count > 100000)
            {
                var oldest = lru.First!.Value;
                var removed = entries[oldest];
                File.Delete(removed.Path); entries.Remove(oldest); lru.RemoveFirst(); residentBytes -= removed.Size;
            }
        }

    }
}
