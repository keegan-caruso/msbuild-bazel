using System.Collections;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

// Sequential Bazel JSON worker. The broker alone sees the host execroot.
internal static class LinuxWorker
{
    internal static bool Isolated { get; private set; }
    private const string Sdk = "/opt/rules_msbuild-toolchain/.tools/dotnet";
    private sealed record WorkInput(string Path, string Digest);
    private sealed record WorkRequest(string[] Arguments, WorkInput[] Inputs, int RequestId = 0, bool Cancel = false);
    private sealed record Reply(int ExitCode, string Output, int RequestId = 0);
    private static readonly JsonSerializerOptions Json = Program.Json;

    internal static async Task<int> Run()
    {
        if (!OperatingSystem.IsLinux() || System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture != System.Runtime.InteropServices.Architecture.Arm64 || Path.GetDirectoryName(Environment.ProcessPath) != Sdk || !File.ReadAllText("/etc/os-release").Contains("VERSION_ID=\"22.04\"", StringComparison.Ordinal))
            throw new InvalidDataException("Explicit workers require the qualified Ubuntu 22.04 ARM64 SDK");
        var execroot = Environment.CurrentDirectory;
        var root = Path.Combine(Path.GetTempPath(), "explicit-worker-" + Guid.NewGuid().ToString("N"));
        foreach (var name in new[] { "in", "out", "tools", "compiler" }) Directory.CreateDirectory(Path.Combine(root, name));
        foreach (var file in Directory.GetFiles(AppContext.BaseDirectory)) File.Copy(file, Path.Combine(root, "tools", Path.GetFileName(file)));
        var store = new SnapshotCache(Path.Combine(root, "cas"));
        using var child = Start(root);
        var errors = child.StandardError.ReadToEndAsync();
        using var stopping = new CancellationTokenSource();
        using var signal = System.Runtime.InteropServices.PosixSignalRegistration.Create(System.Runtime.InteropServices.PosixSignal.SIGTERM, context => { context.Cancel = true; stopping.Cancel(); });
        try
        {
            while (await Console.In.ReadLineAsync().WaitAsync(stopping.Token) is { } line)
            {
                var id = 0; Reply reply;
                try
                {
                    var work = JsonSerializer.Deserialize<WorkRequest>(line, Json)!; id = work.RequestId;
                    if (work.Cancel || work.Arguments is not [var requestPath]) throw new InvalidDataException("Expected one request; worker cancellation is unsupported");
                    var timer = Stopwatch.StartNew();
                    Clear(Path.Combine(root, "in")); Clear(Path.Combine(root, "out"));
                    var identity = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(string.Join('\n', work.Inputs.OrderBy(i => i.Path, StringComparer.Ordinal).Select(i => i.Path + ":" + i.Digest)))));
                    var inputRoot = Path.Combine(root, "in", identity); var raw = Path.Combine(inputRoot, "raw");
                    var declared = new HashSet<string>(StringComparer.Ordinal); store.Begin();
                    foreach (var input in work.Inputs)
                    {
                        Program.Safe(input.Path);
                        if (!declared.Add(input.Path)) throw new InvalidDataException("Duplicate worker input");
                        var source = Path.Combine(execroot, input.Path);
                        // The pinned SDK is a declared tool and read-only execution-platform input.
                        if (Program.Real(source).StartsWith(Sdk + "/", StringComparison.Ordinal)) continue;
                        var digest = Encoding.UTF8.GetString(Convert.FromBase64String(input.Digest));
                        if (digest.Length != 64 || digest.Any(c => !char.IsAsciiHexDigitLower(c))) throw new InvalidDataException("Expected SHA-256 worker input digest");
                        store.Stage(source, Path.Combine(raw, input.Path), digest);
                    }
                    string InputPath(string path)
                    {
                        Program.Safe(path);
                        if (!declared.Any(p => p == path || p.StartsWith(path + "/", StringComparison.Ordinal))) throw new InvalidDataException("Undeclared worker input: " + path);
                        return Path.Combine(raw, path);
                    }
                    var request = JsonSerializer.Deserialize<Request>(File.ReadAllText(InputPath(requestPath)), Json)!;
                    foreach (var output in new[] { request.Reference, request.Runtime, request.Diagnostics })
                    {
                        Program.Safe(output);
                        if (declared.Any(p => p == output || p.StartsWith(output + "/", StringComparison.Ordinal))) throw new InvalidDataException("Worker output overlaps inputs");
                    }
                    Input Map(Input file) => file with { Source = InputPath(file.Source) };
                    var mapped = request with
                    {
                        Project = Map(request.Project),
                        Sources = request.Sources.Select(Map).ToArray(),
                        Imports = request.Imports.Select(Map).ToArray(),
                        Items = request.Items.Select(i => i with { File = Map(i.File) }).ToArray(),
                        References = request.References.Select(InputPath).ToArray(),
                        Packages = request.Packages.Select(p => p with { Directory = InputPath(p.Directory) }).ToArray()
                    };
                    var state = Path.Combine(root, "out", identity);
                    var session = Program.Prepare(mapped, Path.Combine(inputRoot, "workspace"), state) with { ToolRoot = Path.Combine(root, "tools") };
                    var stagingSeconds = timer.Elapsed.TotalSeconds;
                    await child.StandardInput.WriteLineAsync(JsonSerializer.Serialize(session, new JsonSerializerOptions(Json) { WriteIndented = false }));
                    await child.StandardInput.FlushAsync();
                    var response = await child.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromMinutes(10), stopping.Token);
                    if (response is null) throw new IOException("Compiler child exited: " + await errors);
                    reply = JsonSerializer.Deserialize<Reply>(response, Json)! with { RequestId = id };
                    Directory.CreateDirectory(request.Diagnostics);
                    File.WriteAllText(Path.Combine(request.Diagnostics, "build.log"), reply.Output);
                    if (reply.ExitCode == 0)
                    {
                        // Do not publish symlinks emitted by arbitrary project targets.
                        foreach (var file in Directory.EnumerateFileSystemEntries(state, "*", SearchOption.AllDirectories))
                            if (File.GetAttributes(file).HasFlag(FileAttributes.ReparsePoint)) throw new InvalidDataException("Worker output contains a link");
                        Program.Publish(request, state);
                        File.WriteAllText(Path.Combine(request.Diagnostics, "worker.json"), JsonSerializer.Serialize(new { processId = child.Id, identity, stagingSeconds, store.VerifiedBytes, store.ReusedBytes }, Json));
                        if (File.Exists(Path.Combine(state, "compiler.log"))) File.Copy(Path.Combine(state, "compiler.log"), Path.Combine(request.Diagnostics, "compiler.log"), true);
                    }
                }
                catch (Exception error)
                {
                    if (error is TimeoutException && !child.HasExited) child.Kill(true);
                    reply = new Reply(1, error.ToString(), id);
                }
                await Console.Out.WriteLineAsync(JsonSerializer.Serialize(reply, new JsonSerializerOptions(Json) { WriteIndented = false }));
                await Console.Out.FlushAsync();
                if (child.HasExited) return 1;
            }
            return 0;
        }
        catch (OperationCanceledException) when (stopping.IsCancellationRequested) { return 0; }
        finally
        {
            if (!child.HasExited) child.Kill(true);
            await child.WaitForExitAsync();
            Directory.Delete(root, true);
        }
    }
    internal static async Task<int> Child()
    {
        var inputRoot = Environment.GetEnvironmentVariable("EXPLICIT_WORKER_INPUTS") ?? throw new InvalidDataException("Missing worker mount");
        if (!OperatingSystem.IsLinux() || !File.ReadLines("/proc/mounts").Any(line => line.Split(' ') is var parts && parts.Length > 3 && parts[1] == inputRoot && parts[3].Split(',').Contains("ro"))) throw new InvalidDataException("Worker requires read-only input mount");
        Isolated = true;
        var output = Console.Out; var error = Console.Error; var directory = Environment.CurrentDirectory;
        var environment = Environment.GetEnvironmentVariables().Cast<DictionaryEntry>().ToDictionary(e => (string)e.Key, e => (string?)e.Value);
        while (await Console.In.ReadLineAsync() is { } line)
        {
            using var log = new StringWriter(); int exit;
            try
            {
                var session = JsonSerializer.Deserialize<Session>(line, Json)!;
                var start = new ProcessStartInfo(); Sandbox.SetEnvironment(start, session.Workspace, session.State, Sdk);
                foreach (var key in Environment.GetEnvironmentVariables().Keys.Cast<string>().ToArray()) Environment.SetEnvironmentVariable(key, null);
                foreach (var pair in start.Environment) Environment.SetEnvironmentVariable(pair.Key, pair.Value);
                foreach (var key in new[] { "TMPDIR", "TMP", "TEMP" }) Environment.SetEnvironmentVariable(key, Path.Combine(Path.GetDirectoryName(inputRoot)!, "compiler"));
                Environment.SetEnvironmentVariable("RoslynCommandLineLogFile", Path.Combine(session.State, "compiler.log"));
                Console.SetOut(log); Console.SetError(log); Environment.CurrentDirectory = session.Workspace;
                exit = Program.Compile(session);
            }
            catch (Exception exception) { log.WriteLine(exception); exit = 1; }
            finally
            {
                Console.SetOut(output); Console.SetError(error); Environment.CurrentDirectory = directory;
                foreach (var key in Environment.GetEnvironmentVariables().Keys.Cast<string>().ToArray()) Environment.SetEnvironmentVariable(key, null);
                foreach (var pair in environment) Environment.SetEnvironmentVariable(pair.Key, pair.Value);
            }
            await output.WriteLineAsync(JsonSerializer.Serialize(new Reply(exit, log.ToString()), new JsonSerializerOptions(Json) { WriteIndented = false })); await output.FlushAsync();
        }
        return 0;
    }
    private static void Clear(string root)
    {
        foreach (var path in Directory.GetFileSystemEntries(root))
            if (Directory.Exists(path)) Directory.Delete(path, true); else File.Delete(path);
    }
    private static Process Start(string root)
    {
        var start = new ProcessStartInfo("/usr/bin/bwrap") { RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
        void Add(params string[] values) { foreach (var value in values) start.ArgumentList.Add(value); }
        Add("--die-with-parent", "--unshare-all", "--new-session", "--cap-drop", "ALL", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp");
        foreach (var path in new[] { Sdk, "/usr/lib", "/etc/os-release", "/etc/ld.so.cache", "/etc/passwd", "/etc/group", Path.Combine(root, "tools"), Path.Combine(root, "in") }) Add("--ro-bind", path, path);
        Add("--symlink", "usr/lib", "/lib");
        foreach (var name in new[] { "out", "compiler" }) Add("--bind", Path.Combine(root, name), Path.Combine(root, name));
        Add("--chdir", Path.Combine(root, "in"), "--", Sdk + "/dotnet", Path.Combine(root, "tools", "ExplicitBuild.dll"), "--isolated-worker");
        Sandbox.SetEnvironment(start, Path.Combine(root, "in"), Path.Combine(root, "compiler"), Sdk);
        start.Environment["EXPLICIT_WORKER_INPUTS"] = Path.Combine(root, "in");
        return Process.Start(start)!;
    }
}
