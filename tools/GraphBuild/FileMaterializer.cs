using System.Buffers;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using Microsoft.Win32.SafeHandles;

namespace RulesMSBuild.GraphBuild;

internal sealed class FileMaterializer(bool clone, bool profile)
{
    private long ticks;
    private long copies;
    private long clones;
    private long fallbacks;
    private long bytes;
    private long verifiedCopies;
    internal object? Report => profile ? new { seconds = (double)ticks / Stopwatch.Frequency, copies, clones, fallbacks, bytes, verifiedCopies } : null;

    internal void Copy(string source, string destination, string? expectedDigest = null)
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
            if (expectedDigest is null)
            {
                File.Copy(source, destination, overwrite: true);
            }
            else
            {
                CopyVerified(source, destination, expectedDigest);
            }
            if (profile)
            {
                Interlocked.Increment(ref copies);
            }
        }
        if (cloned && expectedDigest is not null && ContractFiles.Digest(destination) != expectedDigest)
        {
            File.Delete(destination);
            throw new InvalidDataException("Corrupt graph snapshot: " + source);
        }
        if (profile)
        {
            if (expectedDigest is not null)
            {
                Interlocked.Increment(ref verifiedCopies);
            }
            Interlocked.Add(ref bytes, new FileInfo(source).Length);
            Interlocked.Add(ref ticks, Stopwatch.GetTimestamp() - start);
        }
    }

    // Verify the bytes actually replayed, without reading the source twice.
    private static void CopyVerified(string source, string destination, string expected)
    {
        var buffer = ArrayPool<byte>.Shared.Rent(128 * 1024);
        try
        {
            using (var input = File.OpenRead(source))
            using (var output = File.Create(destination))
            using (var hash = IncrementalHash.CreateHash(HashAlgorithmName.SHA256))
            {
                int count;
                while ((count = input.Read(buffer)) != 0)
                {
                    hash.AppendData(buffer.AsSpan(0, count));
                    output.Write(buffer.AsSpan(0, count));
                }
                if (Convert.ToHexStringLower(hash.GetHashAndReset()) != expected)
                {
                    throw new InvalidDataException("Corrupt graph snapshot: " + source);
                }
            }
            if (!OperatingSystem.IsWindows())
            {
                File.SetUnixFileMode(destination, File.GetUnixFileMode(source));
            }
            File.SetLastWriteTimeUtc(destination, File.GetLastWriteTimeUtc(source));
        }
        catch
        {
            File.Delete(destination);
            throw;
        }
        finally
        {
            ArrayPool<byte>.Shared.Return(buffer);
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
