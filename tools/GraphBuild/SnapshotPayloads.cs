using System.Collections.Concurrent;
using System.Runtime.InteropServices;
using RulesMSBuild.ProjectCache;

namespace RulesMSBuild.GraphBuild;

// Links are confined to immutable cache entries. Replay always copies/clones to
// writable project outputs, and checks bytes before using an entry.
internal sealed class SnapshotPayloads(string cache) : IProjectCacheContentStore
{
    private readonly ConcurrentDictionary<string, SemaphoreSlim> transfers = new(StringComparer.Ordinal);

    internal void Store(string source, string digest, string destination)
    {
        var blob = Blob(digest);
        try
        {
            Publish(blob, digest, temporary => File.Copy(source, temporary));
        }
        catch (InvalidDataException error)
        {
            throw new InvalidDataException(error.Message + "; source " + source + "; expected " + digest +
                "; current " + ContractFiles.Digest(source), error);
        }
        Link(blob, destination);
    }

    public async Task MaterializeAsync(string digest, Func<CancellationToken, Task<byte[]>> download,
        string[] destinations, CancellationToken cancellationToken)
    {
        var gate = transfers.GetOrAdd(digest, _ => new SemaphoreSlim(1));
        await gate.WaitAsync(cancellationToken);
        try
        {
            var blob = Blob(digest);
            if (!File.Exists(blob))
            {
                var bytes = await download(cancellationToken);
                cancellationToken.ThrowIfCancellationRequested();
                Publish(blob, digest, temporary => File.WriteAllBytes(temporary, bytes));
            }
            else
            {
                Verify(blob, digest);
            }
            foreach (var destination in destinations)
            {
                cancellationToken.ThrowIfCancellationRequested();
                Link(blob, destination);
            }
        }
        finally
        {
            gate.Release();
        }
    }

    private string Blob(string digest)
    {
        if (digest.Length != 64 || digest.Any(character => !char.IsAsciiHexDigitLower(character)))
        {
            throw new InvalidDataException("Invalid snapshot payload digest");
        }
        var directory = Path.Combine(cache, ".cas");
        Directory.CreateDirectory(directory);
        if (new DirectoryInfo(directory).LinkTarget is not null)
        {
            throw new InvalidDataException("Snapshot payload directory must not be a symlink");
        }
        return Path.Combine(directory, digest);
    }

    private static void Publish(string blob, string digest, Action<string> write)
    {
        if (File.Exists(blob))
        {
            Verify(blob, digest);
            return;
        }
        var temporary = blob + ".pending-" + Guid.NewGuid().ToString("N");
        try
        {
            write(temporary);
            Verify(temporary, digest);
            try
            {
                File.Move(temporary, blob);
            }
            catch (IOException) when (File.Exists(blob))
            {
                // Another process may publish the same content concurrently.
                Verify(blob, digest);
            }
        }
        finally
        {
            File.Delete(temporary);
        }
    }

    private static void Verify(string path, string digest)
    {
        if (new FileInfo(path).LinkTarget is not null || ContractFiles.Digest(path) != digest)
        {
            throw new InvalidDataException("Corrupt graph snapshot payload: " + path);
        }
    }

    private static void Link(string source, string destination)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        if ((!OperatingSystem.IsMacOS() && !OperatingSystem.IsLinux()) || LinkFile(source, destination) != 0)
        {
            File.Copy(source, destination);
        }
    }

    [DllImport("libc", EntryPoint = "link", SetLastError = true)]
    private static extern int LinkFile(string source, string destination);
}
