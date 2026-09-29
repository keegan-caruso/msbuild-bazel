using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace RulesMSBuild.GraphBuild;

internal sealed class FileMaterializer(bool clone, bool profile)
{
    private long ticks;
    private long copies;
    private long clones;
    private long fallbacks;
    private long bytes;
    internal object? Report => profile ? new { seconds = (double)ticks / Stopwatch.Frequency, copies, clones, fallbacks, bytes } : null;

    internal void Copy(string source, string destination)
    {
        var start = profile ? Stopwatch.GetTimestamp() : 0;
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        if (clone)
        {
            File.Delete(destination);
        }
        var cloned = clone && TryClone(source, destination);
        if (cloned)
        {
            if (profile)
            {
                Interlocked.Increment(ref clones);
            }
        }
        else
        {
            if (clone && profile)
            {
                Interlocked.Increment(ref fallbacks);
            }
            File.Copy(source, destination, overwrite: true);
            if (profile)
            {
                Interlocked.Increment(ref copies);
            }
        }
        if (profile)
        {
            Interlocked.Add(ref bytes, new FileInfo(source).Length);
            Interlocked.Add(ref ticks, Stopwatch.GetTimestamp() - start);
        }
    }

    private static bool TryClone(string source, string destination)
    {
        if (OperatingSystem.IsMacOS())
        {
            return CloneFile(source, destination, 0) == 0;
        }
        if (OperatingSystem.IsLinux() && IntPtr.Size == 8)
        {
            using var input = File.OpenHandle(source, FileMode.Open, FileAccess.Read);
            using (var output = File.OpenHandle(destination, FileMode.CreateNew, FileAccess.Write))
            {
                if (CloneLinux(output, 0x40049409, input) != 0)
                {
                    return false;
                }
            }
            File.SetUnixFileMode(destination, File.GetUnixFileMode(source));
            File.SetLastWriteTimeUtc(destination, File.GetLastWriteTimeUtc(source));
            return true;
        }
        return false;
    }

    [DllImport("libc", EntryPoint = "clonefile", SetLastError = true)]
    private static extern int CloneFile(string source, string destination, int flags);

    [DllImport("libc", EntryPoint = "ioctl", SetLastError = true)]
    private static extern int CloneLinux(SafeFileHandle destination, ulong request, SafeFileHandle source);
}
