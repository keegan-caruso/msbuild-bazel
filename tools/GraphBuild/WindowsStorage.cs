using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.AccessControl;
using System.Security.Principal;
using Microsoft.Win32.SafeHandles;

namespace RulesMSBuild.GraphBuild;

[SupportedOSPlatform("windows")]
internal static class WindowsStorage
{
    internal static void Permissions(string directory, SecurityIdentifier? profile = null, bool writable = false)
    {
        var owner = new SecurityIdentifier(WindowsProcess.Owner);
        var security = new DirectorySecurity();
        security.SetAccessRuleProtection(true, false);
        security.SetOwner(owner);
        security.AddAccessRule(new FileSystemAccessRule(owner, FileSystemRights.FullControl,
            InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
        if (profile is not null)
        {
            security.AddAccessRule(new FileSystemAccessRule(profile,
                writable ? FileSystemRights.Modify : FileSystemRights.ReadAndExecute,
                InheritanceFlags.ContainerInherit | InheritanceFlags.ObjectInherit, PropagationFlags.None, AccessControlType.Allow));
        }
        new DirectoryInfo(directory).SetAccessControl(security);
    }

    internal static void Integrity(string path, bool low)
    {
        if (!ConvertStringSecurityDescriptorToSecurityDescriptor("S:(ML;OICI;NW;;;" + (low ? "LW" : "ME") + ")",
            1, out var descriptor, out _))
        {
            throw WindowsProcess.Failure("Create sandbox integrity descriptor");
        }
        try
        {
            if (!GetSecurityDescriptorSacl(descriptor, out var present, out var sacl, out _) || !present)
            {
                throw WindowsProcess.Failure("Read sandbox integrity descriptor");
            }
            // LABEL_SECURITY_INFORMATION changes this owned object's mandatory
            // label, without replacing its DACL or requesting a host-wide grant.
            var error = SetNamedSecurityInfo(path, 1, 0x10, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero, sacl);
            if (error != 0)
            {
                throw WindowsProcess.Failure("Set sandbox integrity label", unchecked((int)error));
            }
        }
        finally
        {
            LocalFree(descriptor);
        }
    }

    internal static void IntegrityTree(string root, bool low)
    {
        root = Exact(root);
        Integrity(root, low);
        foreach (var entry in Entries(root))
        {
            Integrity(entry.Path, low);
        }
    }

    internal static int Copy(string source, string destination, bool overwrite = false)
    {
        source = Exact(source);
        destination = Exact(destination);
        Directory.CreateDirectory(destination);
        var count = 0;
        foreach (var entry in Entries(source))
        {
            var target = Path.Combine(destination, entry.Relative.Replace('/', '\\'));
            if (entry.IsDirectory)
            {
                Directory.CreateDirectory(target);
            }
            else
            {
                if (overwrite && LinkCount(entry.Path) != 1)
                {
                    throw new InvalidDataException("Hard link in sandbox output: " + entry.Path);
                }
                if (overwrite && File.Exists(target))
                {
                    var attributes = File.GetAttributes(target);
                    if ((attributes & FileAttributes.ReparsePoint) != 0 || LinkCount(target) != 1)
                    {
                        throw new InvalidDataException("Filesystem alias in sandbox destination: " + target);
                    }
                    File.SetAttributes(target, attributes & ~FileAttributes.ReadOnly);
                }
                File.Copy(entry.Path, target, overwrite);
                count++;
            }
        }
        return count;
    }

    internal static void CopySyncOutputs(string source, string destination)
    {
        var expected = new HashSet<string>(["graph.generated.json", "graph.generated.bzl"], StringComparer.Ordinal);
        foreach (var entry in Entries(Exact(source)))
        {
            if (entry.IsDirectory || !expected.Remove(entry.Relative))
            {
                throw new InvalidDataException("Unexpected sync output: " + entry.Relative);
            }
        }
        if (expected.Count != 0)
        {
            throw new InvalidDataException("Missing generated sync declarations");
        }
        Copy(source, destination, overwrite: true);
    }

    // Only call after the job is empty. Never traverse a task-created junction
    // or symlink during parent-side cleanup, even when it points inside the tree.
    internal static void Delete(string root)
    {
        DeleteExact(Exact(root));
    }

    private static void DeleteExact(string root)
    {
        FileAttributes attributes;
        try
        {
            attributes = File.GetAttributes(root);
        }
        catch (FileNotFoundException)
        {
            return;
        }
        catch (DirectoryNotFoundException)
        {
            return;
        }
        if ((attributes & FileAttributes.ReparsePoint) != 0)
        {
            if ((attributes & FileAttributes.Directory) != 0)
            {
                Directory.Delete(root);
            }
            else
            {
                Unlink(root);
            }
            return;
        }
        if ((attributes & FileAttributes.Directory) != 0)
        {
            foreach (var child in Directory.EnumerateFileSystemEntries(root))
            {
                DeleteExact(child);
            }
            File.SetAttributes(root, attributes & ~FileAttributes.ReadOnly);
            Directory.Delete(root);
        }
        else
        {
            Unlink(root);
        }
    }

    // The task can create NTFS names that ordinary Win32 paths reinterpret as
    // devices or parent segments. Enumerate and remove through verbatim paths;
    // reject those names before copying them into the declared output tree.
    private static string Exact(string path)
    {
        var full = Path.GetFullPath(path);
        return full.StartsWith(@"\\?\", StringComparison.Ordinal) ? full :
            full.StartsWith(@"\\", StringComparison.Ordinal) ? @"\\?\UNC\" + full[2..] : @"\\?\" + full;
    }

    private static IEnumerable<(string Path, string Relative, bool IsDirectory)> Entries(string root, string relative = "")
    {
        if ((File.GetAttributes(root) & FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidDataException("Reparse point in sandbox tree: " + root);
        }
        foreach (var path in Directory.EnumerateFileSystemEntries(root))
        {
            var name = Path.GetFileName(path);
            if (!RelativePathComponents.IsSafeRelative(name, true))
            {
                throw new InvalidDataException("Unsafe sandbox filename: " + path);
            }
            var attributes = File.GetAttributes(path);
            if ((attributes & FileAttributes.ReparsePoint) != 0)
            {
                throw new InvalidDataException("Reparse point in sandbox tree: " + path);
            }
            var child = relative.Length == 0 ? name : relative + "/" + name;
            var directory = (attributes & FileAttributes.Directory) != 0;
            yield return (path, child, directory);
            if (directory)
            {
                foreach (var entry in Entries(path, child))
                {
                    yield return entry;
                }
            }
        }
    }

    private static void Unlink(string path)
    {
        // Unlink without changing attributes shared with another hard link.
        // This Windows 10 1809+ operation also handles readonly files.
        using var handle = CreateFile(path, 0x10000, 7, IntPtr.Zero, 3, 0x00200000, IntPtr.Zero);
        uint disposition = 1 | 2 | 16; // DELETE | POSIX_SEMANTICS | IGNORE_READONLY_ATTRIBUTE
        if (handle.IsInvalid || !SetFileInformationByHandle(handle, 21, ref disposition, sizeof(uint)))
        {
            throw WindowsProcess.Failure("Unlink owned sandbox file");
        }
    }

    private static uint LinkCount(string path)
    {
        using var handle = CreateFile(path, 0x80, 7, IntPtr.Zero, 3, 0x02000000 | 0x00200000, IntPtr.Zero);
        if (handle.IsInvalid || !GetFileInformationByHandle(handle, out var information))
        {
            throw WindowsProcess.Failure("Inspect sandbox file identity");
        }
        if ((information.Attributes & (uint)FileAttributes.ReparsePoint) != 0)
        {
            throw new InvalidDataException("Reparse point in sandbox file: " + path);
        }
        return information.Links;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FileInformation
    {
        internal uint Attributes;
        internal System.Runtime.InteropServices.ComTypes.FILETIME Creation, Access, Write;
        internal uint Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
    }

    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("advapi32.dll", EntryPoint = "ConvertStringSecurityDescriptorToSecurityDescriptorW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string text, int revision, out IntPtr descriptor, out int size);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool GetSecurityDescriptorSacl(IntPtr descriptor, out bool present, out IntPtr sacl, out bool defaulted);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("advapi32.dll", EntryPoint = "SetNamedSecurityInfoW", CharSet = CharSet.Unicode)]
    private static extern uint SetNamedSecurityInfo(string name, int kind, uint information, IntPtr owner, IntPtr group, IntPtr dacl, IntPtr sacl);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr value);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", EntryPoint = "CreateFileW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(string name, uint access, uint share, IntPtr security, uint disposition, uint flags, IntPtr template);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle handle, out FileInformation information);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetFileInformationByHandle(SafeFileHandle handle, int kind, ref uint information, int size);
}
