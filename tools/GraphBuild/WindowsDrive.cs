using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.Principal;

namespace RulesMSBuild.GraphBuild;

// A private directory becomes a readable drive root without granting access to
// the host volume root. The directory ACL, not this alias, enforces isolation.
[SupportedOSPlatform("windows")]
internal sealed class WindowsDrive : IDisposable
{
    internal string Name
    {
        get;
    }
    internal string Target
    {
        get;
    }
    internal string Root => Name + "\\";
    private bool disposed;

    internal WindowsDrive(string directory, Action<string, string> persist)
    {
        directory = Path.GetFullPath(directory);
        if (directory.Length <= 3 || directory[1] != ':' || directory[2] != '\\')
        {
            throw new InvalidDataException("Windows sandbox requires a private directory on a local drive");
        }
        Target = "\\??\\" + directory;
        using var held = new DriveLock();
        foreach (var letter in "ZYXWVUTSRQPONMLKJIHGFED")
        {
            var candidate = letter + ":";
            if (Query(candidate).Length != 0)
            {
                continue;
            }
            // Persist first: a hard termination between DefineDosDevice and
            // constructor completion must still leave an owned cleanup record.
            persist(candidate, Target);
            if (!DefineDosDevice(9, candidate, Target))
            {
                throw WindowsProcess.Failure("Define private sandbox drive");
            }
            var actual = Query(candidate);
            if (actual.Length != 1 || actual[0] != Target)
            {
                Remove(candidate, Target);
                throw new IOException("Sandbox drive allocation collided with another definition");
            }
            Name = candidate;
            return;
        }
        throw new IOException("No unused drive letter is available for Windows filesystem isolation");
    }

    public void Dispose()
    {
        if (!disposed)
        {
            Remove(Name, Target);
            disposed = true;
        }
    }

    internal static void Remove(string name, string target)
    {
        using var held = new DriveLock();
        var before = Query(name);
        var others = before.Where(value => value != target).ToArray();
        foreach (var owned in before.Where(value => value == target))
        {
            // RAW_TARGET_PATH | EXACT_MATCH_ON_REMOVE | REMOVE_DEFINITION |
            // NO_BROADCAST_SYSTEM. Never pop an unspecified drive definition.
            if (!DefineDosDevice(15, name, owned))
            {
                throw WindowsProcess.Failure("Remove private sandbox drive");
            }
        }
        if (!Query(name).SequenceEqual(others, StringComparer.Ordinal))
        {
            throw new IOException("Sandbox drive definitions changed during cleanup; unrelated definitions were not removed");
        }
    }

    internal static string[] Query(string name)
    {
        var buffer = new char[32768];
        var count = QueryDosDevice(name, buffer, buffer.Length);
        if (count == 0)
        {
            var error = Marshal.GetLastPInvokeError();
            if (error == 2)
            {
                return [];
            }
            throw WindowsProcess.Failure("Query sandbox drive", error);
        }
        return new string(buffer, 0, checked((int)count)).TrimEnd('\0').Split('\0');
    }

    internal static string LockName(string resource)
    {
        using var identity = WindowsIdentity.GetCurrent();
        // LocalSystem's DOS devices and storage journal are shared across
        // terminal sessions. Their locks must use the same global scope.
        var scope = identity.User?.IsWellKnown(WellKnownSidType.LocalSystemSid) == true ? "Global" : "Local";
        return scope + "\\RulesMSBuild." + resource + "." + WindowsProcess.Owner;
    }

    private sealed class DriveLock : IDisposable
    {
        private readonly Mutex mutex = new(false, LockName("WindowsDrives"));

        internal DriveLock()
        {
            try
            {
                if (!mutex.WaitOne(TimeSpan.FromSeconds(30)))
                {
                    throw new TimeoutException("Timed out acquiring Windows sandbox drive lease");
                }
            }
            catch (AbandonedMutexException)
            {
                // The mutex is now owned; protected journals recover definitions
                // left by a terminated allocator.
            }
            catch
            {
                mutex.Dispose();
                throw;
            }
        }

        public void Dispose()
        {
            mutex.ReleaseMutex();
            mutex.Dispose();
        }
    }

    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", EntryPoint = "QueryDosDeviceW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint QueryDosDevice(string name, [Out] char[] target, int size);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", EntryPoint = "DefineDosDeviceW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool DefineDosDevice(uint flags, string name, string target);
}
