using System.Runtime.InteropServices;
using System.Runtime.Versioning;

// The OS releases the lease even after SIGKILL. Reclaim abandoned state on the
// next startup; never infer liveness from a PID that the kernel may have reused.
[SupportedOSPlatform("linux")]
internal sealed class WorkerDirectory : IDisposable
{
    private readonly FileStream lease;
    private readonly string leasePath;
    internal string Root
    {
        get;
    }

    [DllImport("libc", EntryPoint = "geteuid")]
    private static extern uint EffectiveUserId();

    // Linux statx has a fixed 256-byte ABI; only the requested UID is consumed.
    [StructLayout(LayoutKind.Explicit, Size = 256)]
    private struct FileStatus
    {
        [FieldOffset(0)] public uint Mask;
        [FieldOffset(20)] public uint UserId;
    }
    [DllImport("libc", EntryPoint = "statx", SetLastError = true)]
    private static extern int Status(int directory, string path, int flags, uint mask, out FileStatus status);

    internal WorkerDirectory()
    {
        var user = EffectiveUserId();
        var parent = Path.Combine(Path.GetTempPath(), "rules-msbuild-workers-" + user.ToString(System.Globalization.CultureInfo.InvariantCulture));
        const UnixFileMode mode = UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute;
        Directory.CreateDirectory(parent, mode);
        // AT_FDCWD, AT_SYMLINK_NOFOLLOW, STATX_UID. Reject pre-created directories
        // owned by another user before looking at any leases beneath them.
        if (Status(-100, parent, 0x100, 0x8, out var status) != 0)
        {
            throw new IOException("Cannot inspect worker state ownership", new System.ComponentModel.Win32Exception(Marshal.GetLastPInvokeError()));
        }
        if ((status.Mask & 0x8) == 0 || status.UserId != user || (File.GetAttributes(parent) & FileAttributes.ReparsePoint) != 0 || File.GetUnixFileMode(parent) != mode)
        {
            throw new InvalidDataException("Worker state requires a private, owned, non-symlink directory: " + parent);
        }
        foreach (var path in Directory.GetFiles(parent, "*.lease"))
        {
            var name = Path.GetFileNameWithoutExtension(path);
            if (!Guid.TryParseExact(name, "N", out _))
            {
                continue;
            }
            try
            {
                if ((File.GetAttributes(path) & FileAttributes.ReparsePoint) != 0)
                {
                    continue;
                }
                using var abandoned = new FileStream(path, FileMode.Open, FileAccess.ReadWrite, FileShare.None);
                Remove(Path.Combine(parent, name), path);
            }
            catch (IOException) { } // An active worker holds the lease, or another reclaimer won.
        }
        var id = Guid.NewGuid().ToString("N");
        Root = Path.Combine(parent, id);
        leasePath = Path.Combine(parent, id + ".lease");
        lease = new FileStream(leasePath, FileMode.CreateNew, FileAccess.ReadWrite, FileShare.None);
        try
        {
            Directory.CreateDirectory(Root);
        }
        catch
        {
            lease.Dispose();
            throw;
        }
    }

    private static void Remove(string root, string leasePath)
    {
        if (Directory.Exists(root))
        {
            if ((File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0)
            {
                throw new InvalidDataException("Worker state must not be a symlink: " + root);
            }
            Directory.Delete(root, true);
        }
        File.Delete(leasePath);
    }

    public void Dispose()
    {
        try
        {
            Remove(Root, leasePath);
        }
        finally
        {
            lease.Dispose();
        }
    }
}
