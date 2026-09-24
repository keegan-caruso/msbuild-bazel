using System.Collections;
using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

// Sequential Bazel JSON worker. The broker alone sees the host execroot.
internal static class LinuxWorker
{
    internal static bool Isolated
    {
        get; private set;
    }
    // Identical inputs see identical physical paths across workers and checkouts.
    // Keep the content identity beneath this root for MSBuild/Roslyn cache safety.
    private const string ChildRoot = "/__rules_msbuild";
    private const string Sdk = "/opt/rules_msbuild-toolchain/.tools/dotnet";
    private sealed record WorkInput(string Path, string Digest);
    private sealed record WorkRequest(string[] Arguments, WorkInput[] Inputs, int RequestId = 0, bool Cancel = false);
    private sealed record Reply(int ExitCode, string Output, int RequestId = 0);
    private static readonly JsonSerializerOptions Json = Program.Json;

    internal static async Task<int> Run(string? toolManifest = null)
    {
        if (!OperatingSystem.IsLinux() || System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture != System.Runtime.InteropServices.Architecture.Arm64 || Path.GetDirectoryName(Environment.ProcessPath) != Sdk || !File.ReadAllText("/etc/os-release").Contains("VERSION_ID=\"22.04\"", StringComparison.Ordinal))
        {
            throw new InvalidDataException("Explicit workers require the qualified Ubuntu 22.04 ARM64 SDK");
        }

        var toolTimer = Stopwatch.StartNew();
        var tools = new WorkerTools(toolManifest, Sdk);
        var startupToolSeconds = toolTimer.Elapsed.TotalSeconds;
        var firstRequest = true;
        var execroot = Environment.CurrentDirectory;
        var root = Path.Combine(Path.GetTempPath(), "explicit-worker-" + Guid.NewGuid().ToString("N"));
        foreach (var name in new[] { "in", "out", "tools", "compiler" })
        {
            Directory.CreateDirectory(Path.Combine(root, name));
        }

        foreach (var file in Directory.GetFiles(AppContext.BaseDirectory))
        {
            File.Copy(file, Path.Combine(root, "tools", Path.GetFileName(file)));
        }

        var store = new SnapshotCache(Path.Combine(root, "cas"));
        using var child = Start(root);
        var errors = child.StandardError.ReadToEndAsync();
        using var stopping = new CancellationTokenSource();
        using var signal = System.Runtime.InteropServices.PosixSignalRegistration.Create(System.Runtime.InteropServices.PosixSignal.SIGTERM, context => { context.Cancel = true; stopping.Cancel(); });
        try
        {
            while (await Console.In.ReadLineAsync().WaitAsync(stopping.Token) is { } line)
            {
                var id = 0;
                Reply reply;
                try
                {
                    var work = JsonSerializer.Deserialize<WorkRequest>(line, Json)!;
                    id = work.RequestId;
                    if (work.Cancel || work.Arguments is not [var requestPath])
                    {
                        throw new InvalidDataException("Expected one request; worker cancellation is unsupported");
                    }

                    var timer = Stopwatch.StartNew();
                    Clear(Path.Combine(root, "in"));
                    Clear(Path.Combine(root, "out"));
                    var identity = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(string.Join('\n', work.Inputs.Where(i => !tools.Contains(i.Path)).OrderBy(i => i.Path, StringComparer.Ordinal).Select(i => i.Path + ":" + i.Digest)))));
                    var identitySeconds = timer.Elapsed.TotalSeconds;
                    var inputRoot = Path.Combine(root, "in", identity);
                    var raw = Path.Combine(inputRoot, "raw");
                    var declared = new HashSet<string>(StringComparer.Ordinal);
                    var declaredDirectories = new HashSet<string>(StringComparer.Ordinal);
                    store.Begin();
                    double snapshotFileSeconds = 0;
                    var toolInputs = 0;
                    var stagedInputs = 0;
                    foreach (var input in work.Inputs)
                    {
                        if (!declared.Add(input.Path))
                        {
                            throw new InvalidDataException("Duplicate worker input");
                        }

                        for (var parent = Path.GetDirectoryName(input.Path); !string.IsNullOrEmpty(parent) && declaredDirectories.Add(parent); parent = Path.GetDirectoryName(parent))
                        {
                        }
                        var source = Path.Combine(execroot, input.Path);
                        // Tools already exist in the child's immutable startup mounts.
                        // Exact inventory membership replaces per-request filesystem probing.
                        if (tools.Contains(input.Path))
                        {
                            toolInputs++;
                            continue;
                        }
                        Program.Safe(input.Path);
                        var digest = Encoding.UTF8.GetString(Convert.FromBase64String(input.Digest));
                        if (digest.Length != 64 || digest.Any(c => !char.IsAsciiHexDigitLower(c)))
                        {
                            throw new InvalidDataException("Expected SHA-256 worker input digest");
                        }

                        var probe = Stopwatch.GetTimestamp();
                        store.Stage(source, Path.Combine(raw, input.Path), digest);
                        snapshotFileSeconds += Stopwatch.GetElapsedTime(probe).TotalSeconds;
                        stagedInputs++;
                    }
                    var snapshotSeconds = timer.Elapsed.TotalSeconds - identitySeconds;
                    string InputPath(string path)
                    {
                        Program.Safe(path);
                        if (!declared.Contains(path) && !declaredDirectories.Contains(path))
                        {
                            throw new InvalidDataException("Undeclared worker input: " + path);
                        }

                        return Path.Combine(raw, path);
                    }
                    var request = JsonSerializer.Deserialize<Request>(File.ReadAllText(InputPath(requestPath)), Json)!;
                    foreach (var output in new[] { request.Reference, request.Runtime, request.Diagnostics }.Concat(request.RestoreProjectOutput is null ? [] : new[] { request.RestoreProjectOutput }).Concat(request.TargetOutput is null ? [] : new[] { request.TargetOutput }).Concat(request.GeneratedOutputs?.Values ?? Enumerable.Empty<string>()))
                    {
                        Program.Safe(output);
                        if (declared.Contains(output) || declaredDirectories.Contains(output))
                        {
                            throw new InvalidDataException("Worker output overlaps inputs");
                        }
                    }
                    var mapped = MapInputs(request, InputPath);
                    var state = Path.Combine(root, "out", identity);
                    string ChildPath(string path) => path.StartsWith(root + "/", StringComparison.Ordinal) ? ChildRoot + path[root.Length..] : path;
                    var prepared = BuildPreparation.Prepare(mapped, Path.Combine(inputRoot, "workspace"), state, ChildPath);
                    var session = prepared with
                    {
                        Request = MapInputs(mapped, ChildPath),
                        Workspace = ChildPath(prepared.Workspace),
                        State = ChildPath(state),
                        Original = ChildPath(prepared.Original),
                        ToolRoot = ChildRoot + "/tools"
                    };
                    var stagingSeconds = timer.Elapsed.TotalSeconds;
                    await child.StandardInput.WriteLineAsync(JsonSerializer.Serialize(session, new JsonSerializerOptions(Json) { WriteIndented = false }));
                    await child.StandardInput.FlushAsync();
                    var response = await child.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromMinutes(10), stopping.Token);
                    if (response is null)
                    {
                        throw new IOException("Compiler child exited: " + await errors);
                    }

                    reply = JsonSerializer.Deserialize<Reply>(response, Json)! with
                    {
                        RequestId = id
                    };
                    var childSeconds = timer.Elapsed.TotalSeconds - stagingSeconds;
                    Directory.CreateDirectory(request.Diagnostics);
                    File.WriteAllText(Path.Combine(request.Diagnostics, "build.log"), reply.Output);
                    if (reply.ExitCode == 0)
                    {
                        // Do not publish symlinks emitted by arbitrary project targets.
                        foreach (var file in Directory.EnumerateFileSystemEntries(state, "*", SearchOption.AllDirectories))
                        {
                            if (File.GetAttributes(file).HasFlag(FileAttributes.ReparsePoint))
                            {
                                throw new InvalidDataException("Worker output contains a link");
                            }
                        }

                        BuildOutputs.Publish(request, state);
                        File.WriteAllText(Path.Combine(request.Diagnostics, "worker.json"), JsonSerializer.Serialize(new
                        {
                            processId = child.Id,
                            identity,
                            stagingSeconds,
                            identitySeconds,
                            snapshotSeconds,
                            preparationSeconds = stagingSeconds - identitySeconds - snapshotSeconds,
                            childSeconds,
                            publicationSeconds = timer.Elapsed.TotalSeconds - stagingSeconds - childSeconds,
                            snapshotFileSeconds,
                            toolInputs,
                            stagedInputs,
                            startupToolSeconds = firstRequest ? startupToolSeconds : 0,
                            toolInventoryCount = tools.Count,
                            store.VerifiedBytes,
                            store.ReusedBytes,
                            store.ReusedFiles
                        }, Json));
                        if (File.Exists(Path.Combine(state, "compiler.log")))
                        {
                            File.Copy(Path.Combine(state, "compiler.log"), Path.Combine(request.Diagnostics, "compiler.log"), true);
                        }
                    }
                }
                catch (Exception error)
                {
                    if (error is TimeoutException && !child.HasExited)
                    {
                        child.Kill(true);
                    }

                    reply = new Reply(1, error.ToString(), id);
                }
                firstRequest = false;
                await Console.Out.WriteLineAsync(JsonSerializer.Serialize(reply, new JsonSerializerOptions(Json) { WriteIndented = false }));
                await Console.Out.FlushAsync();
                if (child.HasExited)
                {
                    return 1;
                }
            }
            return 0;
        }
        catch (OperationCanceledException) when (stopping.IsCancellationRequested) { return 0; }
        finally
        {
            if (!child.HasExited)
            {
                child.Kill(true);
            }

            await child.WaitForExitAsync();
            Directory.Delete(root, true);
        }
    }
    private static Request MapInputs(Request request, Func<string, string> map)
    {
        Input Map(Input file) => file with
        {
            Source = map(file.Source)
        };
        return request with
        {
            Project = Map(request.Project),
            RestoreInput = request.RestoreInput is null ? null : map(request.RestoreInput),
            Sources = request.Sources.Select(Map).ToArray(),
            Imports = request.Imports.Select(Map).ToArray(),
            AdapterImports = request.AdapterImports?.Select(Map).ToArray(),
            Items = request.Items.Select(i => i with { File = Map(i.File) }).ToArray(),
            References = request.References.Select(map).ToArray(),
            RuntimeReferences = request.RuntimeReferences?.Select(map).ToArray(),
            FrameworkInputs = request.FrameworkInputs?.Select(map).ToArray(),
            LayoutBindings = request.LayoutBindings?.Select(b => b with { Directory = map(b.Directory) }).ToArray(),
            RestoreProjects = request.RestoreProjects?.Select(map).ToArray(),
            TargetInputs = request.TargetInputs?.Select(i => i with { File = map(i.File) }).ToArray(),
            BuildTools = request.BuildTools?.Select(t => t with { Directories = t.Directories.Select(map).ToArray(), Packages = t.Packages?.Select(p => p with { Directory = map(p.Directory) }).ToArray(), Data = t.Data.Select(d => d with { Source = map(d.Source) }).ToArray() }).ToArray(),
            ProjectAnalyzers = request.ProjectAnalyzers?.Select(a => a with { Directories = a.Directories.Select(map).ToArray(), Packages = a.Packages?.Select(p => p with { Directory = map(p.Directory) }).ToArray() }).ToArray(),
            ProjectOutputs = request.ProjectOutputs?.Select(p => p with { Directory = p.Directory is null ? null : map(p.Directory), File = p.File is null ? null : map(p.File) }).ToArray(),
            Packages = request.Packages.Select(p => p with { Directory = map(p.Directory) }).ToArray()
        };
    }
    internal static async Task<int> Child()
    {
        var inputRoot = Environment.GetEnvironmentVariable("EXPLICIT_WORKER_INPUTS") ?? throw new InvalidDataException("Missing worker mount");
        if (!OperatingSystem.IsLinux() || !File.ReadLines("/proc/mounts").Any(line => line.Split(' ') is var parts && parts.Length > 3 && parts[1] == inputRoot && parts[3].Split(',').Contains("ro")))
        {
            throw new InvalidDataException("Worker requires read-only input mount");
        }

        Isolated = true;
        var output = Console.Out;
        var error = Console.Error;
        var directory = Environment.CurrentDirectory;
        var environment = Environment.GetEnvironmentVariables().Cast<DictionaryEntry>().ToDictionary(e => (string)e.Key, e => (string?)e.Value);
        while (await Console.In.ReadLineAsync() is { } line)
        {
            using var log = new StringWriter();
            int exit;
            try
            {
                var session = JsonSerializer.Deserialize<Session>(line, Json)!;
                var start = new ProcessStartInfo();
                Sandbox.SetEnvironment(start, session.Workspace, session.State, Sdk);
                foreach (var key in Environment.GetEnvironmentVariables().Keys.Cast<string>().ToArray())
                {
                    Environment.SetEnvironmentVariable(key, null);
                }

                foreach (var pair in start.Environment)
                {
                    Environment.SetEnvironmentVariable(pair.Key, pair.Value);
                }

                foreach (var key in new[] { "TMPDIR", "TMP", "TEMP" })
                {
                    Environment.SetEnvironmentVariable(key, Path.Combine(Path.GetDirectoryName(inputRoot)!, "compiler"));
                }

                Environment.SetEnvironmentVariable("RoslynCommandLineLogFile", Path.Combine(session.State, "compiler.log"));
                Console.SetOut(log);
                Console.SetError(log);
                Environment.CurrentDirectory = session.Workspace;
                exit = ProjectCompilation.Compile(session);
            }
            catch (Exception exception) { log.WriteLine(exception); exit = 1; }
            finally
            {
                Console.SetOut(output);
                Console.SetError(error);
                Environment.CurrentDirectory = directory;
                foreach (var key in Environment.GetEnvironmentVariables().Keys.Cast<string>().ToArray())
                {
                    Environment.SetEnvironmentVariable(key, null);
                }

                foreach (var pair in environment)
                {
                    Environment.SetEnvironmentVariable(pair.Key, pair.Value);
                }
            }
            await output.WriteLineAsync(JsonSerializer.Serialize(new Reply(exit, log.ToString()), new JsonSerializerOptions(Json) { WriteIndented = false }));
            await output.FlushAsync();
        }
        return 0;
    }
    private static void Clear(string root)
    {
        foreach (var path in Directory.GetFileSystemEntries(root))
        {
            if (Directory.Exists(path))
            {
                Directory.Delete(path, true);
            }
            else
            {
                File.Delete(path);
            }
        }
    }
    private static Process Start(string root)
    {
        var start = new ProcessStartInfo("/usr/bin/bwrap") { RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
        void Add(params string[] values)
        {
            foreach (var value in values)
            {
                start.ArgumentList.Add(value);
            }
        }
        Add("--die-with-parent", "--unshare-all", "--new-session", "--cap-drop", "ALL", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp");
        foreach (var path in new[] { Sdk, "/usr/lib", "/etc/os-release", "/etc/ld.so.cache", "/etc/passwd", "/etc/group" })
        {
            Add("--ro-bind", path, path);
        }

        foreach (var name in new[] { "tools", "in" })
        {
            Add("--ro-bind", Path.Combine(root, name), Path.Combine(ChildRoot, name));
        }

        Add("--symlink", "usr/lib", "/lib");
        foreach (var name in new[] { "out", "compiler" })
        {
            Add("--bind", Path.Combine(root, name), Path.Combine(ChildRoot, name));
        }

        Add("--chdir", Path.Combine(ChildRoot, "in"), "--", Sdk + "/dotnet", Path.Combine(ChildRoot, "tools", "ExplicitBuild.dll"), "--isolated-worker");
        Sandbox.SetEnvironment(start, Path.Combine(ChildRoot, "in"), Path.Combine(ChildRoot, "compiler"), Sdk);
        start.WorkingDirectory = Path.Combine(root, "in");
        start.Environment["EXPLICIT_WORKER_INPUTS"] = Path.Combine(ChildRoot, "in");
        return Process.Start(start)!;
    }
}
