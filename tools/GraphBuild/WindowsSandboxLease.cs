using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.Win32.SafeHandles;

namespace RulesMSBuild.GraphBuild;

// Control records are outside the directory granted to the AppContainer. A
// cancelled task cannot forge a cleanup request for another path or profile.
[SupportedOSPlatform("windows")]
internal sealed class WindowsSandboxLease : IDisposable
{
    private sealed record Journal(int Version, int Owner, long OwnerStart, int? Child = null, long? ChildStart = null, string? Drive = null);
    private static readonly JsonSerializerOptions Json = new() { UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow };
    private readonly string id = Guid.NewGuid().ToString("N");
    private readonly string request;
    private Journal journal;
    private readonly WindowsProfile? profile;
    private WindowsDrive? drive;
    private bool disposed;
    internal string Action
    {
        get;
    }
    internal string Root => drive?.Root ?? throw new InvalidOperationException("Sandbox drive is not allocated");
    internal WindowsProfile Profile => profile ?? throw new InvalidOperationException("Sandbox profile is not created");
    internal string JobName => Job(id);

    internal WindowsSandboxLease()
    {
        var storage = Storage();
        using var owner = Process.GetCurrentProcess();
        journal = new Journal(1, owner.Id, owner.StartTime.ToUniversalTime().Ticks);
        using (var held = new StorageLock())
        {
            Directory.CreateDirectory(storage);
            WindowsStorage.Permissions(storage);
            foreach (var previous in Directory.EnumerateDirectories(storage))
            {
                if (!Guid.TryParseExact(Path.GetFileName(previous), "N", out _) ||
                    (File.GetAttributes(previous) & FileAttributes.ReparsePoint) != 0)
                {
                    continue;
                }
                var record = Path.Combine(previous, "control", "lease.json");
                if (!File.Exists(record))
                {
                    continue;
                }
                var state = JsonSerializer.Deserialize<Journal>(File.ReadAllText(record), Json)
                    ?? throw new InvalidDataException("Empty Windows sandbox lease");
                if (state.Version != 1)
                {
                    throw new InvalidDataException("Unsupported Windows sandbox lease version");
                }
                if (!Alive(state.Owner, state.OwnerStart))
                {
                    Cleanup(previous, state);
                }
            }
            request = Path.Combine(storage, id);
            Directory.CreateDirectory(Path.Combine(request, "control"));
            WindowsStorage.Permissions(request);
            Action = Directory.CreateDirectory(Path.Combine(request, "action")).FullName;
            WindowsStorage.Permissions(Action);
            Save();
        }
        try
        {
            profile = new WindowsProfile(ProfileName(id));
        }
        catch
        {
            // A failed create must not delete a profile that it did not own.
            // No drive or child can exist before the profile is created.
            WindowsStorage.Delete(request);
            throw;
        }
    }

    internal void AllocateDrive() => drive = new WindowsDrive(Action, (name, _) =>
    {
        journal = journal with
        {
            Drive = name
        };
        Save();
    });

    internal void Started(int pid)
    {
        using var child = Process.GetProcessById(pid);
        journal = journal with
        {
            Child = pid,
            ChildStart = child.StartTime.ToUniversalTime().Ticks
        };
        Save();
    }

    private void Save()
    {
        var target = Path.Combine(request, "control", "lease.json");
        var temporary = target + ".tmp";
        File.WriteAllText(temporary, JsonSerializer.Serialize(journal));
        File.Move(temporary, target, true);
    }

    public void Dispose()
    {
        if (disposed)
        {
            return;
        }
        // Keep the protected journal on any failure; a later invocation can
        // retry without trusting paths or process IDs supplied by a task.
        CleanupJob(id, journal);
        if (drive is not null)
        {
            drive.Dispose();
        }
        else if (journal.Drive is not null)
        {
            RemoveDrive(request, journal.Drive);
        }
        if (profile is not null)
        {
            profile.Dispose();
        }
        // Also retry a previous Dispose failure, whose SID handle is already
        // closed. Keep the journal until profile removal has succeeded.
        RemoveProfile(id);
        WindowsStorage.Delete(request);
        disposed = true;
    }

    private static void Cleanup(string directory, Journal state)
    {
        var identifier = Path.GetFileName(directory);
        CleanupJob(identifier, state);
        if (state.Drive is not null)
        {
            RemoveDrive(directory, state.Drive);
        }
        RemoveProfile(identifier);
        WindowsStorage.Delete(directory);
    }

    private static void RemoveDrive(string directory, string name)
    {
        if (name.Length != 2 || name[0] is < 'D' or > 'Z' || name[1] != ':')
        {
            throw new InvalidDataException("Invalid drive in Windows sandbox lease");
        }
        WindowsDrive.Remove(name, "\\??\\" + Path.Combine(directory, "action"));
    }

    private static void CleanupJob(string identifier, Journal state)
    {
        var value = OpenJobObject(0xc, false, Job(identifier));
        if (value != IntPtr.Zero)
        {
            using var job = new WindowsProcess.KernelHandle(value);
            WindowsProcess.StopJob(job);
        }
        else if (Marshal.GetLastPInvokeError() != 2)
        {
            throw WindowsProcess.Failure("Open owned sandbox job during cleanup");
        }
        if (state.Child is { } pid && state.ChildStart is { } time && Alive(pid, time))
        {
            try
            {
                using var child = Process.GetProcessById(pid);
                if (!child.WaitForExit(5000))
                {
                    throw new IOException("Sandbox child is still running; cleanup record retained");
                }
            }
            catch (ArgumentException) { } // The recorded child exited after Alive.
        }
    }

    private static bool Alive(int pid, long time)
    {
        try
        {
            using var process = Process.GetProcessById(pid);
            return !process.HasExited && process.StartTime.ToUniversalTime().Ticks == time;
        }
        catch (ArgumentException)
        {
            return false;
        }
        catch (InvalidOperationException)
        {
            // The process can exit between HasExited and StartTime.
            return false;
        }
    }

    private static string ProfileName(string identifier) => "RulesMSBuild.Graph." + identifier;
    private static string Job(string identifier) => "Global\\RulesMSBuild.Graph." + identifier;

    private static void RemoveProfile(string identifier)
    {
        var error = WindowsProfile.DeleteAppContainerProfile(ProfileName(identifier));
        if (error is not (0 or unchecked((int)0x80070002) or unchecked((int)0x80070490)))
        {
            Marshal.ThrowExceptionForHR(error);
        }
    }

    private static string Storage()
    {
        using var identity = WindowsIdentity.GetCurrent();
        uint length = 0;
        GetUserProfileDirectory(identity.AccessToken, null, ref length);
        var path = new StringBuilder(checked((int)length));
        if (!GetUserProfileDirectory(identity.AccessToken, path, ref length))
        {
            throw WindowsProcess.Failure("Locate persistent sandbox control directory");
        }
        var statistics = new byte[56];
        if (!GetTokenInformation(identity.AccessToken, 10, statistics, statistics.Length, out _))
        {
            throw WindowsProcess.Failure("Read sandbox logon namespace");
        }
        // LocalSystem defines global DOS devices. Other logons have separate
        // DOS namespaces, even when their user SID is the same.
        var logon = identity.User?.IsWellKnown(WellKnownSidType.LocalSystemSid) == true
            ? "system" : BitConverter.ToUInt64(statistics, 8).ToString("x16", System.Globalization.CultureInfo.InvariantCulture);
        var storage = Path.Combine(path.ToString(), "AppData", "Local", "rules-msbuild", "windows-sandbox-v1", logon);
        for (var current = storage; current is not null; current = Path.GetDirectoryName(current))
        {
            if (Path.Exists(current) && (File.GetAttributes(current) & FileAttributes.ReparsePoint) != 0)
            {
                throw new InvalidDataException("Windows sandbox control directory cannot have reparse-point ancestors");
            }
        }
        var root = Path.GetPathRoot(storage)!;
        if (root.Length != 3 || root[1] != ':' || new DriveInfo(root).DriveFormat != "NTFS")
        {
            throw new InvalidDataException("Windows filesystem isolation requires local NTFS control storage");
        }
        return storage;
    }

    private sealed class StorageLock : IDisposable
    {
        private readonly Mutex mutex = new(false, WindowsDrive.LockName("WindowsStorage"));
        internal StorageLock()
        {
            try
            {
                if (!mutex.WaitOne(TimeSpan.FromSeconds(30)))
                {
                    throw new TimeoutException("Timed out acquiring Windows sandbox control storage");
                }
            }
            catch (AbandonedMutexException) { }
            catch { mutex.Dispose(); throw; }
        }
        public void Dispose()
        {
            mutex.ReleaseMutex();
            mutex.Dispose();
        }
    }

    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", EntryPoint = "OpenJobObjectW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr OpenJobObject(uint access, bool inherit, string name);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("userenv.dll", EntryPoint = "GetUserProfileDirectoryW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool GetUserProfileDirectory(SafeAccessTokenHandle token, StringBuilder? path, ref uint size);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool GetTokenInformation(SafeAccessTokenHandle token, int kind, [Out] byte[] data, int size, out int returned);
}
