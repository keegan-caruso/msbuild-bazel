using System.Runtime.InteropServices;

namespace RulesMSBuild.GraphBuild;

// Only a read-only bind of the same verified files can replace copying and the
// final package-content pass. This is not a timestamp or manifest-only shortcut.
internal static class ReadOnlyPackageTree
{
    [StructLayout(LayoutKind.Explicit, Size = 112)]
    private struct FileSystemStatus
    {
        [FieldOffset(72)] public ulong Flags;
    }

    [StructLayout(LayoutKind.Explicit, Size = 256)]
    private struct FileStatus
    {
        [FieldOffset(0)] public uint Mask;
        [FieldOffset(32)] public ulong Inode;
        [FieldOffset(136)] public uint DeviceMajor;
        [FieldOffset(140)] public uint DeviceMinor;
    }

    [DllImport("libc", EntryPoint = "statvfs", SetLastError = true)]
    private static extern int FileSystem(string path, out FileSystemStatus status);

    [DllImport("libc", EntryPoint = "statx", SetLastError = true)]
    private static extern int Status(int directory, string path, int flags, uint mask, out FileStatus status);

    internal static bool SameVolume(string left, string right) => OperatingSystem.IsLinux() &&
        Status(-100, left, 0x100, 0x100, out var first) == 0 && Status(-100, right, 0x100, 0x100, out var second) == 0 &&
        first.DeviceMajor == second.DeviceMajor && first.DeviceMinor == second.DeviceMinor;

    internal static bool Contains(string relative) => relative.StartsWith(".nuget/", StringComparison.Ordinal);

    internal static void RequireReadOnly(string root)
    {
        if (!OperatingSystem.IsLinux() || IntPtr.Size != 8 || FileSystem(root, out var status) != 0 || (status.Flags & 1) == 0)
        {
            throw new InvalidDataException("Prepared package reuse requires a read-only Linux mount: " + root);
        }
    }

    internal static void RequireSameFile(string source, string destination, int mode)
    {
        if (!OperatingSystem.IsLinux() || Status(-100, source, 0x100, 0x100, out var left) != 0 || Status(-100, destination, 0x100, 0x100, out var right) != 0 ||
            (left.Mask & right.Mask & 0x100) == 0 || left.Inode != right.Inode || left.DeviceMajor != right.DeviceMajor || left.DeviceMinor != right.DeviceMinor ||
            (int)File.GetUnixFileMode(destination) != mode)
        {
            throw new InvalidDataException("Prepared package mount does not match verified content and mode: " + destination);
        }
    }
}
