using System.ComponentModel;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Runtime.Versioning;
using System.Security.Principal;
using System.Text;
using Microsoft.Win32.SafeHandles;

namespace RulesMSBuild.GraphBuild;

// This is a headless AppContainer launch, not a shell or a task replacement.
// A job is assigned atomically at creation; only the three pipe ends are inherited.
[SupportedOSPlatform("windows")]
internal static class WindowsProcess
{
    private static readonly object DesktopGate = new();
    internal static async Task<int> Run(WindowsProfile profile, string jobName, string application,
        IEnumerable<string> arguments, string directory, IReadOnlyDictionary<string, string> environment,
        Action<int> started, CancellationToken cancellationToken, Stream? standardOutput = null, Stream? standardError = null)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var command = new StringBuilder(CommandLine(application, arguments));
        var environmentBlock = EnvironmentBlock(environment);
        using var desktop = new PrivateDesktop(profile.Identifier.Value);
        using var job = NewJob(jobName);
        using var output = new AnonymousPipeServerStream(PipeDirection.In, HandleInheritability.Inheritable);
        using var error = new AnonymousPipeServerStream(PipeDirection.In, HandleInheritability.Inheritable);
        using var input = new AnonymousPipeServerStream(PipeDirection.Out, HandleInheritability.Inheritable);
        using var capabilities = NativeBuffer.Struct(new SecurityCapabilities { Sid = profile.Sid.DangerousGetHandle() });
        using var jobs = NativeBuffer.Pointers(job.DangerousGetHandle());
        using var handles = NativeBuffer.Pointers(input.ClientSafePipeHandle.DangerousGetHandle(),
            output.ClientSafePipeHandle.DangerousGetHandle(), error.ClientSafePipeHandle.DangerousGetHandle());
        using var attributes = new ProcessAttributes(3);
        attributes.Set(0x20009, capabilities);
        attributes.Set(0x2000d, jobs);
        attributes.Set(0x20002, handles);
        using var desktopName = NativeBuffer.Text(desktop.Name);
        using var variables = NativeBuffer.Text(environmentBlock);
        var startup = new StartupInfoEx
        {
            Startup = new StartupInfo
            {
                Size = Marshal.SizeOf<StartupInfoEx>(),
                Desktop = desktopName.DangerousGetHandle(),
                Flags = 0x100,
                Input = input.ClientSafePipeHandle.DangerousGetHandle(),
                Output = output.ClientSafePipeHandle.DangerousGetHandle(),
                Error = error.ClientSafePipeHandle.DangerousGetHandle()
            },
            Attributes = attributes.Pointer
        };
        // Suspended startup permits recording the child in the protected lease
        // before any SDK code executes. JOB_LIST avoids the assignment race.
        var launched = CreateProcess(application, command, IntPtr.Zero,
            IntPtr.Zero, true, 0x80404, variables.DangerousGetHandle(), directory, ref startup, out var created);
        var launchError = Marshal.GetLastPInvokeError();
        attributes.Dispose();
        // SECURITY_CAPABILITIES contains a raw SID pointer; retain its owner
        // until CreateProcess has copied the attribute into the child token.
        GC.KeepAlive(profile);
        if (!launched)
        {
            throw Failure("Create AppContainer process", launchError);
        }
        using var process = new KernelHandle(created.Process);
        using var thread = new KernelHandle(created.Thread);
        output.DisposeLocalCopyOfClientHandle();
        error.DisposeLocalCopyOfClientHandle();
        input.Dispose(); // No interactive input or inherited host stdin.
        using var drain = new CancellationTokenSource();
        var readers = Task.WhenAll(output.CopyToAsync(standardOutput ?? Console.OpenStandardOutput(), drain.Token),
            error.CopyToAsync(standardError ?? Console.OpenStandardError(), drain.Token));
        try
        {
            started(created.Id);
            cancellationToken.ThrowIfCancellationRequested();
            if (ResumeThread(thread) == uint.MaxValue)
            {
                throw Failure("Resume AppContainer process");
            }
            using var exited = new ProcessWait(process);
            await Task.Run(() => WaitHandle.WaitAny([exited, cancellationToken.WaitHandle]), CancellationToken.None);
            cancellationToken.ThrowIfCancellationRequested();
            if (!GetExitCodeProcess(process, out var code))
            {
                throw Failure("Read AppContainer exit status");
            }
            return unchecked((int)code);
        }
        finally
        {
            // Also stop compiler servers or other descendants after normal exit.
            try
            {
                StopJob(job);
            }
            finally
            {
                job.Dispose();
                try
                {
                    await readers.WaitAsync(TimeSpan.FromSeconds(5));
                }
                finally
                {
                    drain.Cancel();
                    WorkerProcess.Observe(readers);
                }
            }
        }
    }

    internal static string CommandLine(string application, IEnumerable<string> arguments) =>
        string.Join(' ', new[] { application }.Concat(arguments).Select(Quote));

    private static string Quote(string value)
    {
        if (value.Contains('\0'))
        {
            throw new InvalidDataException("NUL in Windows process argument");
        }
        var result = new StringBuilder("\"");
        var slashes = 0;
        foreach (var character in value)
        {
            if (character == '\\')
            {
                slashes++;
                continue;
            }
            result.Append('\\', character == '"' ? slashes * 2 + 1 : slashes);
            result.Append(character);
            slashes = 0;
        }
        return result.Append('\\', slashes * 2).Append('"').ToString();
    }

    private static string EnvironmentBlock(IReadOnlyDictionary<string, string> environment)
    {
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var (name, value) in environment)
        {
            if (name.Length == 0 || name.Contains('=') || name.Contains('\0') || value.Contains('\0') || !names.Add(name))
            {
                throw new InvalidDataException("Invalid or duplicate Windows environment variable");
            }
        }
        return string.Join('\0', environment.OrderBy(pair => pair.Key, StringComparer.OrdinalIgnoreCase)
            .Select(pair => pair.Key + "=" + pair.Value)) + "\0\0";
    }

    private static KernelHandle NewJob(string name)
    {
        using var descriptor = new SecurityDescriptor("D:P(A;;GA;;;" + Owner + ")");
        var security = descriptor.Attributes;
        var value = CreateJobObject(ref security, name);
        var existing = Marshal.GetLastPInvokeError() == 183;
        var job = new KernelHandle(value);
        if (job.IsInvalid)
        {
            throw Failure("Create sandbox job");
        }
        if (existing)
        {
            job.Dispose();
            throw new IOException("Sandbox job name already exists");
        }
        var limits = new ExtendedLimits { Basic = new BasicLimits { Flags = 0x2000 } };
        if (!SetInformationJobObject(job, 9, ref limits, Marshal.SizeOf<ExtendedLimits>()))
        {
            var failure = Failure("Configure sandbox job");
            job.Dispose();
            throw failure;
        }
        return job;
    }

    internal static void StopJob(KernelHandle job)
    {
        if (!TerminateJobObject(job, 125))
        {
            throw Failure("Terminate sandbox job");
        }
        var deadline = Environment.TickCount64 + 5000;
        while (true)
        {
            if (!QueryInformationJobObject(job, 1, out var accounting, Marshal.SizeOf<JobAccounting>(), IntPtr.Zero))
            {
                throw Failure("Query sandbox job");
            }
            if (accounting.ActiveProcesses == 0)
            {
                return;
            }
            if (Environment.TickCount64 >= deadline)
            {
                throw new IOException("Sandbox descendants did not exit after job termination");
            }
            Thread.Sleep(10);
        }
    }

    internal static string Owner
    {
        get
        {
            using var identity = WindowsIdentity.GetCurrent();
            return identity.User?.Value ?? throw new IOException("Windows sandbox requires a user identity");
        }
    }

    internal static Win32Exception Failure(string operation, int? code = null)
    {
        var error = code ?? Marshal.GetLastPInvokeError();
        return new Win32Exception(error, operation + ": " + new Win32Exception(error).Message);
    }

    internal sealed class KernelHandle : SafeHandleZeroOrMinusOneIsInvalid
    {
        internal KernelHandle(IntPtr value) : base(true) => SetHandle(value);
        protected override bool ReleaseHandle() => CloseHandle(handle);
    }

    private sealed class ProcessWait : WaitHandle
    {
        internal ProcessWait(KernelHandle process) => SafeWaitHandle = new SafeWaitHandle(process.DangerousGetHandle(), false);
    }

    private sealed class ProcessAttributes : IDisposable
    {
        private readonly NativeBuffer memory;
        private bool disposed;
        internal IntPtr Pointer => memory.DangerousGetHandle();

        internal ProcessAttributes(int count)
        {
            var size = IntPtr.Zero;
            InitializeProcThreadAttributeList(IntPtr.Zero, count, 0, ref size);
            memory = new NativeBuffer(checked((int)size));
            if (!InitializeProcThreadAttributeList(Pointer, count, 0, ref size))
            {
                var failure = Failure("Initialize sandbox process attributes");
                memory.Dispose();
                throw failure;
            }
        }

        internal void Set(int key, NativeBuffer value)
        {
            if (!UpdateProcThreadAttribute(Pointer, 0, new IntPtr(key), value.DangerousGetHandle(),
                new IntPtr(value.Size), IntPtr.Zero, IntPtr.Zero))
            {
                throw Failure("Set sandbox process attribute");
            }
        }

        public void Dispose()
        {
            if (disposed)
            {
                return;
            }
            disposed = true;
            DeleteProcThreadAttributeList(Pointer);
            memory.Dispose();
        }
    }

    internal sealed class NativeBuffer : SafeHandleZeroOrMinusOneIsInvalid
    {
        internal int Size
        {
            get;
        }

        internal NativeBuffer(int size) : base(true)
        {
            Size = size;
            SetHandle(Marshal.AllocHGlobal(size));
        }

        internal static NativeBuffer Text(string text)
        {
            var characters = (text + '\0').ToCharArray();
            var result = new NativeBuffer(checked(characters.Length * sizeof(char)));
            Marshal.Copy(characters, 0, result.handle, characters.Length);
            return result;
        }

        internal static NativeBuffer Struct<T>(T value) where T : struct
        {
            var result = new NativeBuffer(Marshal.SizeOf<T>());
            Marshal.StructureToPtr(value, result.handle, false);
            return result;
        }

        internal static NativeBuffer Pointers(params IntPtr[] values)
        {
            var result = new NativeBuffer(checked(values.Length * IntPtr.Size));
            for (var index = 0; index < values.Length; index++)
            {
                Marshal.WriteIntPtr(result.handle, index * IntPtr.Size, values[index]);
            }
            return result;
        }

        protected override bool ReleaseHandle()
        {
            Marshal.FreeHGlobal(handle);
            return true;
        }
    }

    private sealed class SecurityDescriptor : IDisposable
    {
        private readonly IntPtr pointer;
        internal SecurityAttributes Attributes => new() { Size = Marshal.SizeOf<SecurityAttributes>(), Descriptor = pointer };

        internal SecurityDescriptor(string sddl)
        {
            if (!ConvertStringSecurityDescriptorToSecurityDescriptor(sddl, 1, out pointer, out _))
            {
                throw Failure("Create sandbox security descriptor");
            }
        }

        public void Dispose() => LocalFree(pointer);
    }

    private sealed class PrivateDesktop : IDisposable
    {
        private readonly IntPtr station;
        private readonly IntPtr desktop;
        internal string Name
        {
            get;
        }

        internal PrivateDesktop(string sid)
        {
            using var descriptor = new SecurityDescriptor("D:P(A;;GA;;;" + Owner + ")(A;;GA;;;" + sid + ")S:(ML;;NW;;;LW)");
            var security = descriptor.Attributes;
            var name = "RulesMSBuild_" + Guid.NewGuid().ToString("N");
            station = CreateWindowStation(name, 0, 0x10000000, ref security);
            if (station == IntPtr.Zero)
            {
                throw Failure("Create private sandbox window station");
            }
            try
            {
                // Window-station selection is process-global, including across
                // independent callers preparing different private desktops.
                lock (DesktopGate)
                {
                    var previous = GetProcessWindowStation();
                    var previousDesktop = GetThreadDesktop(GetCurrentThreadId());
                    if (previous == IntPtr.Zero)
                    {
                        throw Failure("Read window station");
                    }
                    if (previousDesktop == IntPtr.Zero)
                    {
                        throw Failure("Read thread desktop");
                    }
                    if (!SetProcessWindowStation(station))
                    {
                        throw Failure("Select private sandbox window station");
                    }
                    try
                    {
                        desktop = CreateDesktop("default", IntPtr.Zero, IntPtr.Zero, 0, 0x10000000, ref security);
                    }
                    finally
                    {
                        if (!SetProcessWindowStation(previous))
                        {
                            throw Failure("Restore window station");
                        }
                        // CreateDesktop also assigns the calling thread. That
                        // borrowed original handle must be restored, not closed.
                        if (!SetThreadDesktop(previousDesktop))
                        {
                            throw Failure("Restore thread desktop");
                        }
                    }
                }
                if (desktop == IntPtr.Zero)
                {
                    throw Failure("Create private sandbox desktop");
                }
            }
            catch
            {
                if (desktop != IntPtr.Zero)
                {
                    CloseDesktop(desktop);
                }
                CloseWindowStation(station);
                throw;
            }
            Name = name + "\\default";
        }

        public void Dispose()
        {
            var desktopClosed = CloseDesktop(desktop);
            var desktopError = Marshal.GetLastPInvokeError();
            var stationClosed = CloseWindowStation(station);
            if (!desktopClosed)
            {
                throw Failure("Close private sandbox desktop", desktopError);
            }
            if (!stationClosed)
            {
                throw Failure("Close private sandbox window station");
            }
        }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct StartupInfo
    {
        public int Size;
        public IntPtr Reserved, Desktop, Title;
        public int X, Y, Width, Height, XCharacters, YCharacters, Fill, Flags;
        public short Show, ReservedLength;
        public IntPtr ReservedPointer, Input, Output, Error;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct StartupInfoEx
    {
        public StartupInfo Startup; public IntPtr Attributes;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct ProcessInformation
    {
        public IntPtr Process, Thread; public int Id, ThreadId;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct SecurityCapabilities
    {
        public IntPtr Sid, Capabilities; public int Count, Reserved;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct SecurityAttributes
    {
        public int Size; public IntPtr Descriptor; public int Inherit;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct BasicLimits
    {
        public long ProcessTime, JobTime;
        public uint Flags;
        public UIntPtr MinimumWorkingSet, MaximumWorkingSet;
        public uint ProcessLimit;
        public UIntPtr Affinity;
        public uint Priority, Scheduling;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters
    {
        public ulong ReadOperations, WriteOperations, OtherOperations, ReadBytes, WriteBytes, OtherBytes;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct ExtendedLimits
    {
        public BasicLimits Basic; public IoCounters Io; public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct JobAccounting
    {
        public long UserTime, KernelTime, PeriodUserTime, PeriodKernelTime;
        public uint PageFaults, TotalProcesses, ActiveProcesses, TerminatedProcesses;
    }

    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", EntryPoint = "CreateProcessW", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool CreateProcess(string application, StringBuilder command, IntPtr processSecurity, IntPtr threadSecurity, bool inherit, uint flags, IntPtr environment, string directory, ref StartupInfoEx startup, out ProcessInformation process);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool CloseHandle(IntPtr handle);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", SetLastError = true)] private static extern uint ResumeThread(KernelHandle thread);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool GetExitCodeProcess(KernelHandle process, out uint code);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", EntryPoint = "CreateJobObjectW", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr CreateJobObject(ref SecurityAttributes security, string name);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool SetInformationJobObject(KernelHandle job, int kind, ref ExtendedLimits limits, int size);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool QueryInformationJobObject(KernelHandle job, int kind, out JobAccounting accounting, int size, IntPtr returned);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool TerminateJobObject(KernelHandle job, uint code);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool InitializeProcThreadAttributeList(IntPtr list, int count, int flags, ref IntPtr size);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll", SetLastError = true)] private static extern bool UpdateProcThreadAttribute(IntPtr list, uint flags, IntPtr key, IntPtr value, IntPtr size, IntPtr previous, IntPtr returned);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll")] private static extern void DeleteProcThreadAttributeList(IntPtr list);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr value);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("advapi32.dll", EntryPoint = "ConvertStringSecurityDescriptorToSecurityDescriptorW", CharSet = CharSet.Unicode, SetLastError = true)] private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptor(string text, int revision, out IntPtr descriptor, out int size);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("user32.dll", EntryPoint = "CreateWindowStationW", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr CreateWindowStation(string name, uint flags, uint access, ref SecurityAttributes security);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr GetProcessWindowStation();
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("user32.dll", SetLastError = true)] private static extern bool SetProcessWindowStation(IntPtr station);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("kernel32.dll")] private static extern uint GetCurrentThreadId();
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("user32.dll", SetLastError = true)] private static extern IntPtr GetThreadDesktop(uint thread);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("user32.dll", SetLastError = true)] private static extern bool SetThreadDesktop(IntPtr desktop);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("user32.dll", EntryPoint = "CreateDesktopW", CharSet = CharSet.Unicode, SetLastError = true)] private static extern IntPtr CreateDesktop(string name, IntPtr device, IntPtr mode, uint flags, uint access, ref SecurityAttributes security);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("user32.dll", SetLastError = true)] private static extern bool CloseDesktop(IntPtr desktop);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("user32.dll", SetLastError = true)] private static extern bool CloseWindowStation(IntPtr station);
}

[SupportedOSPlatform("windows")]
internal sealed class WindowsProfile : IDisposable
{
    private bool disposed;
    internal string Name
    {
        get;
    }
    internal SidHandle Sid
    {
        get;
    }
    internal SecurityIdentifier Identifier
    {
        get;
    }

    internal WindowsProfile(string name)
    {
        Name = name;
        Marshal.ThrowExceptionForHR(CreateAppContainerProfile(name, name, "MSBuild graph action", IntPtr.Zero, 0, out var sid));
        Sid = new SidHandle(sid);
        try
        {
            Identifier = new SecurityIdentifier(sid);
        }
        catch
        {
            DeleteAppContainerProfile(name);
            Sid.Dispose();
            throw;
        }
    }

    public void Dispose()
    {
        if (disposed)
        {
            return;
        }
        disposed = true;
        try
        {
            Marshal.ThrowExceptionForHR(DeleteAppContainerProfile(Name));
        }
        finally
        {
            Sid.Dispose();
        }
    }

    internal sealed class SidHandle : SafeHandleZeroOrMinusOneIsInvalid
    {
        internal SidHandle(IntPtr value) : base(true) => SetHandle(value);
        protected override bool ReleaseHandle() => FreeSid(handle) == IntPtr.Zero;
    }

    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("userenv.dll", CharSet = CharSet.Unicode)] private static extern int CreateAppContainerProfile(string name, string display, string description, IntPtr capabilities, int count, out IntPtr sid);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("userenv.dll", CharSet = CharSet.Unicode)] internal static extern int DeleteAppContainerProfile(string name);
    [DefaultDllImportSearchPaths(DllImportSearchPath.System32)]
    [DllImport("advapi32.dll")] private static extern IntPtr FreeSid(IntPtr sid);
}
