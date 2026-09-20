using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using ActionRunner;

// The broker is trusted; project tasks run only in its read-allowlisted child.
// One outstanding request, no multiplexing and no cancellation protocol.
internal static class LinuxWorker
{
    internal const string Sdk = "/opt/rules_msbuild-toolchain/.tools/dotnet";
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
    private sealed record Input(string Path, string Digest);
    private sealed record Request(string[] Arguments, Input[] Inputs, int RequestId = 0, bool Cancel = false);
    private sealed record Response(int ExitCode, string Output, int RequestId = 0);
    internal static bool Isolated { get; private set; }
    internal const string CompilerTemp = "/worker/compiler";

    internal static async Task<int> Child()
    {
        // Never permit this switch to silently turn an ordinary action into a trusted worker.
        if (!OperatingSystem.IsLinux() || !File.ReadLines("/proc/mounts").Any(line =>
                line.Split(' ') is var parts && parts.Length > 3 && parts[1] == "/worker/in" && parts[3].Split(',').Contains("ro")))
            throw new InvalidDataException("The compiler worker requires its read-only input mount");
        Isolated = true;
        Program.ConfigureEngine();
        return await WorkerProbe.Run();
    }

    internal static void BeginRequest()
    {
        if (!Isolated) return;
        Files.ReadOnlyInputs = JsonSerializer.Deserialize<Dictionary<string, Files.VerifiedInput>>(File.ReadAllText("/worker/in/.worker-inputs.json"), Json);
        Files.ReadOnlyHits = 0; Files.HashedBytes = 0;
    }

    internal static void EndRequest(string requestPath)
    {
        if (!Isolated) return;
        var request = JsonSerializer.Deserialize<RunnerRequest>(File.ReadAllText(requestPath), Json)!;
        if (Directory.Exists(request.Diagnostics)) File.WriteAllText(Path.Combine(request.Diagnostics, "input-validation.json"), JsonSerializer.Serialize(new { readOnlyHits = Files.ReadOnlyHits, hashedBytes = Files.HashedBytes }, Json));
        Files.ReadOnlyInputs = null;
    }

    internal static async Task<int> Run(bool reuseInputs = true)
    {
        if (!OperatingSystem.IsLinux() || System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture != System.Runtime.InteropServices.Architecture.Arm64 ||
            Path.GetDirectoryName(Environment.ProcessPath) != Sdk || !File.ReadAllText("/etc/os-release").Contains("VERSION_ID=\"22.04\"", StringComparison.Ordinal))
            throw new InvalidDataException("Persistent compilation requires the qualified Ubuntu 22.04 ARM64 SDK");
        var execroot = Environment.CurrentDirectory;
        // Keep the mount roots themselves alive for the entire child's lifetime.
        var root = Path.Combine(Path.GetTempPath(), ".msbuild-worker-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(root);
        foreach (var name in new[] { "in", "out", "compiler", "tools" }) Directory.CreateDirectory(Path.Combine(root, name));
        var runner = typeof(Program).Assembly.Location;
        foreach (var path in Directory.EnumerateFiles(Path.GetDirectoryName(runner)!))
            Files.Copy(path, Path.Combine(root, "tools", Path.GetFileName(path)));
        var store = new WorkerInputs(Path.Combine(root, "cas"), reuseInputs);
        using var child = Start(root);
        var errors = child.StandardError.ReadToEndAsync();
        using var stopping = new CancellationTokenSource();
        using var terminate = System.Runtime.InteropServices.PosixSignalRegistration.Create(System.Runtime.InteropServices.PosixSignal.SIGTERM, context => { context.Cancel = true; stopping.Cancel(); });
        try
        {
            while (await Console.In.ReadLineAsync().WaitAsync(stopping.Token) is { } line)
            {
                var id = 0;
                Response response;
                try
                {
                    var request = JsonSerializer.Deserialize<Request>(line, Json) ?? throw new InvalidDataException("Missing worker request");
                    id = request.RequestId;
                    if (request.Cancel || request.Arguments is not [var requestPath]) throw new InvalidDataException("Expected one request file; cancellation is unsupported");
                    var timer = Stopwatch.StartNew();
                    Clear(Path.Combine(root, "in")); Clear(Path.Combine(root, "out"));
                    var identity = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(string.Join('\n', request.Inputs.OrderBy(i => i.Path, StringComparer.Ordinal).Select(i => i.Path + ":" + i.Digest)))));
                    var inputRoot = Path.Combine(root, "in", identity);
                    var inputPrefix = "/worker/in/" + identity + "/";
                    var declared = new HashSet<string>(StringComparer.Ordinal);
                    store.Begin();
                    var identities = new Dictionary<string, Files.VerifiedInput>(StringComparer.Ordinal);
                    foreach (var input in request.Inputs)
                    {
                        if (!Files.ValidRelativePath(input.Path) || !declared.Add(input.Path)) throw new InvalidDataException("Invalid or duplicate worker input: " + input.Path);
                        var source = Path.Combine(execroot, input.Path);
                        // The pinned SDK is an explicit, read-only part of the execution platform.
                        var real = new FileInfo(source).ResolveLinkTarget(true)?.FullName ?? source;
                        if (real.StartsWith(Sdk + "/", StringComparison.Ordinal)) continue;
                        var digest = Encoding.UTF8.GetString(Convert.FromBase64String(input.Digest));
                        if (digest.Length != 64 || digest.Any(c => !char.IsAsciiHexDigitLower(c))) throw new InvalidDataException("Expected Bazel SHA-256 input identity");
                        var target = Path.Combine(inputRoot, input.Path);
                        identities.Add(inputPrefix + input.Path, store.Stage(source, target, digest));
                    }
                    if (!declared.Contains(requestPath)) throw new InvalidDataException("Request is not a declared input");
                    var original = JsonSerializer.Deserialize<RunnerRequest>(File.ReadAllText(Path.Combine(inputRoot, requestPath)), Json)!;
                    if (!original.ProjectAction) throw new InvalidDataException("Worker accepts only per-project compilation");
                    // Bundle/package identities keep shared reference paths stable
                    // across consumers, but change them when any adjacent input
                    // changes. Only this request's groups are visible in the child.
                    var groups = (original.Prebuilt ?? []).Concat((original.PackageDirectories ?? []).Select(p => p.Source))
                        .Distinct(StringComparer.Ordinal).ToDictionary(p => p, _ => new List<Input>(), StringComparer.Ordinal);
                    if (groups.Keys.Any(p => !Files.ValidRelativePath(p))) throw new InvalidDataException("Invalid prepared input group");
                    string? Group(string path)
                    {
                        for (var current = path; !string.IsNullOrEmpty(current); current = Path.GetDirectoryName(current))
                            if (groups.ContainsKey(current)) return current;
                        return null;
                    }
                    foreach (var group in groups.Keys)
                        if (Group(Path.GetDirectoryName(group) ?? "") is not null) throw new InvalidDataException("Overlapping prepared input groups");
                    foreach (var input in request.Inputs)
                        if (Group(input.Path) is { } group) groups[group].Add(input);
                    var preparedRoots = new Dictionary<string, string>(StringComparer.Ordinal);
                    foreach (var (group, members) in groups)
                    {
                        if (members.Count == 0 || members.Any(p => p.Path == group)) throw new InvalidDataException("Prepared input group must contain declared files");
                        var version = Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes("prepared-tree\n" + string.Join('\n', members.OrderBy(i => i.Path, StringComparer.Ordinal).Select(i => i.Path + ":" + i.Digest)))));
                        var alias = Path.Combine(root, "in", version, group);
                        Directory.CreateDirectory(Path.GetDirectoryName(alias)!);
                        Directory.CreateSymbolicLink(alias, Path.GetRelativePath(Path.GetDirectoryName(alias)!, Path.Combine(inputRoot, group)));
                        var prefix = "/worker/in/" + version + "/";
                        preparedRoots.Add(group, prefix);
                        foreach (var member in members) identities.Add(prefix + member.Path, identities[inputPrefix + member.Path]);
                    }
                    string In(string path)
                    {
                        if (!Files.ValidRelativePath(path) || !declared.Any(p => p == path || p.StartsWith(path + "/", StringComparison.Ordinal))) throw new InvalidDataException("Undeclared action input: " + path);
                        return (Group(path) is { } group ? preparedRoots[group] : inputPrefix) + path;
                    }
                    // Distinct content gets distinct compiler metadata-cache paths, even if
                    // source timestamps and sizes happen to be identical.
                    var destination = "/worker/out/" + identity;
                    var mapped = original with
                    {
                        Output = destination + "/bundle",
                        Diagnostics = destination + "/diagnostics",
                        ApiOutput = destination + "/api",
                        RuntimeOutput = original.RuntimeOutput is null ? null : destination + "/runtime",
                        Manifest = In(original.Manifest),
                        Restore = In(original.Restore),
                        PreparedPlan = original.PreparedPlan is null ? null : In(original.PreparedPlan),
                        Sources = original.Sources.Select(f => f with { Source = In(f.Source) }).ToArray(),
                        Seeds = original.Seeds.Select(f => f with { Source = In(f.Source) }).ToArray(),
                        Prebuilt = original.Prebuilt?.Select(In).ToArray(),
                        PackageDirectories = original.PackageDirectories?.Select(p => p with { Source = In(p.Source) }).ToArray()
                    };
                    var mappedPath = Path.Combine(root, "in", ".worker-request.json");
                    if (File.Exists(mappedPath)) throw new InvalidDataException("Reserved input path");
                    File.WriteAllText(mappedPath, JsonSerializer.Serialize(mapped, Json));
                    var indexPath = Path.Combine(root, "in", ".worker-inputs.json");
                    if (File.Exists(indexPath)) throw new InvalidDataException("Reserved input path");
                    File.WriteAllText(indexPath, JsonSerializer.Serialize(reuseInputs ? identities : null, Json));
                    var stagingSeconds = timer.Elapsed.TotalSeconds;
                    await child.StandardInput.WriteLineAsync(JsonSerializer.Serialize(new { RequestPath = "/worker/in/.worker-request.json", WorkingDirectory = "/worker/in" }));
                    await child.StandardInput.FlushAsync();
                    var reply = await child.StandardOutput.ReadLineAsync().WaitAsync(TimeSpan.FromMinutes(10), stopping.Token);
                    if (reply is null) throw new IOException("Compiler worker exited: " + await errors);
                    response = JsonSerializer.Deserialize<Response>(reply, Json)! with { RequestId = id };
                    var actionRoot = Path.Combine(root, "out", identity);
                    void Export(string name, string? path)
                    {
                        if (path is null || !Directory.Exists(Path.Combine(actionRoot, name))) return;
                        if (!Files.ValidRelativePath(path) || declared.Any(p => p == path || p.StartsWith(path + "/", StringComparison.Ordinal))) throw new InvalidDataException("Unsafe action output");
                        var source = Path.Combine(actionRoot, name);
                        foreach (var entry in Directory.EnumerateFileSystemEntries(source, "*", SearchOption.AllDirectories))
                            if (File.GetAttributes(entry).HasFlag(FileAttributes.ReparsePoint)) throw new InvalidDataException("Worker output contains a link");
                        Files.CopyTree(source, Path.Combine(execroot, path));
                    }
                    Export("diagnostics", original.Diagnostics);
                    if (response.ExitCode == 0)
                    {
                        Export("bundle", original.Output); Export("api", original.ApiOutput); Export("runtime", original.RuntimeOutput);
                        File.WriteAllText(Path.Combine(execroot, original.Diagnostics, "worker.json"), JsonSerializer.Serialize(new { stagingSeconds, verifiedBytes = store.VerifiedBytes, reusedBytes = store.ReusedBytes, reusedFiles = store.ReusedFiles, processId = child.Id, identity, preparedRoots }, Json));
                    }
                }
                catch (Exception error)
                {
                    if (error is TimeoutException && !child.HasExited) child.Kill(true);
                    response = new Response(1, error.ToString(), id);
                }
                await Console.Out.WriteLineAsync(JsonSerializer.Serialize(response, Json));
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

    private static void Clear(string root)
    {
        foreach (var path in Directory.EnumerateFileSystemEntries(root))
            if (Directory.Exists(path)) Directory.Delete(path, true); else File.Delete(path);
    }

    private static Process Start(string root)
    {
        var start = new ProcessStartInfo("/usr/bin/bwrap") { RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true };
        void Add(params string[] args) { foreach (var arg in args) start.ArgumentList.Add(arg); }
        Add("--die-with-parent", "--unshare-all", "--new-session", "--cap-drop", "ALL", "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp");
        foreach (var path in new[] { Sdk, "/usr/lib" }) Add("--ro-bind", path, path);
        foreach (var path in new[] { "/etc/os-release", "/etc/ld.so.cache", "/etc/passwd", "/etc/group" }) Add("--ro-bind", path, path);
        Add("--symlink", "usr/lib", "/lib");
        Add("--ro-bind", Path.Combine(root, "tools"), "/worker/tools", "--ro-bind", Path.Combine(root, "in"), "/worker/in");
        Add("--bind", Path.Combine(root, "out"), "/worker/out", "--bind", Path.Combine(root, "compiler"), CompilerTemp, "--chdir", "/worker/in");
        Add("--", Sdk + "/dotnet", "/worker/tools/NativeProjectCache.dll", "--isolated-worker");
        start.Environment.Clear();
        foreach (var (key, value) in NativeCache.PortableEnvironment.Create(Sdk, CompilerTemp, CompilerTemp, "/worker/in")) start.Environment[key] = value;
        start.Environment["DOTNET_EnableDiagnostics"] = "0";
        return Process.Start(start)!;
    }
}
