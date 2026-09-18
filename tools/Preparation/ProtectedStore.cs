using System.Runtime.InteropServices;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace RulesMSBuild.Preparation;

// Opt-in process-local trust in the privileged Nix administrator and storage.
// Never persist verification receipts; restart after administrative store repair.
internal sealed class ProtectedStore
{
    private readonly Dictionary<string, (string Signature, JsonObject Snapshot)> saved = new(StringComparer.Ordinal);
    public int Hits { get; private set; }
    public int FullScans { get; private set; }
    public int Roots => saved.Count;
    private sealed record Status(uint Device, ushort Mode, ulong Inode, uint User, long Modified, long Changed, long Born);
    private static Status? Stat(string path)
    {
        var buffer = Marshal.AllocHGlobal(256);
        try
        {
            if (LStat(path, buffer) != 0) return null;
            return new((uint)Marshal.ReadInt32(buffer), (ushort)Marshal.ReadInt16(buffer, 4), (ulong)Marshal.ReadInt64(buffer, 8), (uint)Marshal.ReadInt32(buffer, 16), Marshal.ReadInt64(buffer, 48), Marshal.ReadInt64(buffer, 64), Marshal.ReadInt64(buffer, 80));
        }
        finally { Marshal.FreeHGlobal(buffer); }
    }
    private static bool NoAcl(string path)
    {
        var acl = AclGet(path, 0x100);
        if (acl == IntPtr.Zero) return Marshal.GetLastPInvokeError() == 2;
        AclFree(acl); return false;
    }
    private static bool Protected(string path, Status? info) => info is not null && info.User == 0 && ((info.Mode & 0xf000) == 0xa000 || (info.Mode & 0x12) == 0) && NoAcl(path);
    internal static bool Eligible(string root)
    {
        if (!OperatingSystem.IsMacOS() || GetEuid() == 0 || Path.GetDirectoryName(root) != "/nix/store" || !Regex.IsMatch(Path.GetFileName(root), "^[0-9abcdfghijklmnpqrsvwxyz]{32}-.+$", RegexOptions.CultureInvariant)) return false;
        foreach (var parent in new[] { "/", "/nix", "/nix/store" })
        {
            var info = Stat(parent);
            if (info is null || info.User != 0 || (info.Mode & 0xf000) != 0x4000 || !NoAcl(parent) || ((info.Mode & 0x12) != 0 && !(parent == "/nix/store" && (info.Mode & 0x200) != 0))) return false;
        }
        var status = Stat(root);
        return status is not null && (status.Mode & 0xf000) == 0x4000 && Protected(root, status);
    }
    private static bool TreeProtected(string root)
    {
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var parents = new HashSet<string>(StringComparer.Ordinal);
        bool Visit(string path)
        {
            if (!Host.Within(path, "/nix/store") || path == "/nix/store") return false;
            if (!seen.Add(path)) return true;
            var info = Stat(path);
            if (!Protected(path, info)) return false;
            for (var parent = Path.GetDirectoryName(path); parent != "/nix/store"; parent = Path.GetDirectoryName(parent!))
            {
                if (parent is null) return false;
                if (!parents.Add(parent)) break;
                if (!Protected(parent, Stat(parent))) return false;
                var resolved = Host.Real(parent);
                if (!Host.Within(resolved, "/nix/store")) return false;
                for (var actual = resolved; actual != "/nix/store"; actual = Path.GetDirectoryName(actual)!)
                    if (!Protected(actual, Stat(actual))) return false;
            }
            var type = info!.Mode & 0xf000;
            if (type == 0xa000)
            {
                // Check every link in a chain, not merely its final target.
                var target = new FileInfo(path).LinkTarget;
                return target is not null && Visit(Path.GetFullPath(Path.Combine(Path.GetDirectoryName(path)!, target)));
            }
            if (type == 0x4000) return Directory.EnumerateFileSystemEntries(path).All(Visit);
            return type == 0x8000;
        }
        return Visit(root);
    }
    public JsonObject Snapshot(string root, Func<JsonObject> fullScan)
    {
        if (!Eligible(root)) { saved.Remove(root); FullScans++; return fullScan(); }
        var signature = Stat(root)!.ToString();
        if (saved.TryGetValue(root, out var cached) && cached.Signature == signature)
        {
            Hits++; return (JsonObject)cached.Snapshot.DeepClone();
        }
        saved.Remove(root);
        var eligible = TreeProtected(root);
        FullScans++; var snapshot = fullScan();
        if (eligible && Eligible(root) && Stat(root)!.ToString() == signature) saved[root] = (signature, (JsonObject)snapshot.DeepClone());
        return snapshot;
    }
    [DllImport("libc", EntryPoint = "lstat", SetLastError = true)]
    private static extern int LStat(string path, IntPtr buffer);
    [DllImport("libc", EntryPoint = "geteuid")]
    private static extern uint GetEuid();
    [DllImport("libc", EntryPoint = "acl_get_link_np", SetLastError = true)]
    private static extern IntPtr AclGet(string path, int type);
    [DllImport("libc", EntryPoint = "acl_free")]
    private static extern int AclFree(IntPtr acl);
}
