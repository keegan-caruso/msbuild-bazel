using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace RulesMSBuild.GraphBuild;

// Persistent transport/cache broker. Reviewed contracts can also retain a
// sandboxed evaluation engine; every request still gets fresh workspace contents.
internal static class GraphWorker
{
    private sealed record Input(string Path, string Digest = "");
    private sealed record WorkRequest(string[] Arguments, Input[] Inputs, int RequestId = 0, bool Cancel = false);
    private sealed record Reply(int ExitCode, string Output, int RequestId = 0);
    private sealed record Source(string Path, string Destination);
    private sealed record Request(string Contract, string Output, string Target, string? Prepared, Source[] Sources, bool ProfileBuild = false, int EvaluationCacheMb = 512);
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    internal static async Task<int> Run(string[] args)
    {
        if (!OperatingSystem.IsLinux() || args.Length != 3)
        {
            throw new InvalidDataException("Graph worker requires Linux, sandbox tool, cache budget and one request parameter file");
        }
        var sandbox = Path.GetFullPath(args[0]);
        if (!int.TryParse(args[1], System.Globalization.NumberStyles.None, System.Globalization.CultureInfo.InvariantCulture, out var megabytes) || megabytes < 0)
        {
            throw new InvalidDataException("Graph worker cache budget must be a nonnegative MiB count");
        }
        var cacheBudget = (long)megabytes * 1024 * 1024;
        var execroot = Environment.CurrentDirectory;
        using var directory = new WorkerDirectory();
        using var engine = new WorkerEngine(directory.Root);
        var cache = Path.Combine(directory.Root, "cache");
        Directory.CreateDirectory(cache);
        var preparationCache = Path.Combine(directory.Root, "preparations");
        Directory.CreateDirectory(preparationCache);
        var persistent = args[2] == "--persistent_worker";
        if (!persistent)
        {
            if (!args[2].StartsWith('@'))
            {
                throw new InvalidDataException("Expected @request parameter file");
            }
            var lines = File.ReadAllLines(args[2][1..]);
            if (lines.Length != 1)
            {
                throw new InvalidDataException("Expected one graph request");
            }
            var result = await Build(lines[0], null);
            Console.Error.Write(result.Output);
            return result.ExitCode;
        }
        while (await Console.In.ReadLineAsync() is { } line)
        {
            var id = 0;
            Reply reply;
            try
            {
                var work = JsonSerializer.Deserialize<WorkRequest>(line, Json) ?? throw new InvalidDataException("Missing worker request");
                id = work.RequestId;
                if (work.Cancel || work.Arguments.Length != 1)
                {
                    throw new InvalidDataException("Expected one graph request; cancellation is unsupported");
                }
                var declared = work.Inputs.Select(input => Safe(input.Path)).ToHashSet(StringComparer.Ordinal);
                reply = (await Build(work.Arguments[0], declared, work.Inputs.ToDictionary(input => input.Path, input => input.Digest, StringComparer.Ordinal))) with
                {
                    RequestId = id
                };
            }
            catch (Exception error)
            {
                engine.Stop();
                reply = new(1, error.ToString(), id);
            }
            await Console.Out.WriteLineAsync(JsonSerializer.Serialize(reply, Json));
            await Console.Out.FlushAsync();
        }
        return 0;

        async Task<Reply> Build(string requestPath, HashSet<string>? declared, Dictionary<string, string>? inputDigests = null)
        {
            string InputPath(string path)
            {
                Safe(path);
                if (declared is not null && !declared.Contains(path) && !declared.Any(input => input.StartsWith(path + "/", StringComparison.Ordinal)))
                {
                    throw new InvalidDataException("Undeclared worker input: " + path);
                }
                return Path.Combine(execroot, path);
            }
            var request = JsonSerializer.Deserialize<Request>(File.ReadAllText(InputPath(requestPath)), Json)
                ?? throw new InvalidDataException("Missing graph action request");
            var requestTimer = request.ProfileBuild ? Stopwatch.StartNew() : null;
            var stageSeconds = 0.0;
            var childSeconds = 0.0;
            var verificationSeconds = 0.0;
            var publicationSeconds = 0.0;
            var succeeded = false;
            var contract = InputPath(request.Contract);
            var prepared = request.Prepared is null ? "-" : InputPath(request.Prepared);
            var output = Path.Combine(execroot, Safe(request.Output));
            if (declared is not null && declared.Any(input => input == request.Output || input.StartsWith(request.Output + "/", StringComparison.Ordinal) || request.Output.StartsWith(input + "/", StringComparison.Ordinal)))
            {
                throw new InvalidDataException("Graph output overlaps worker inputs");
            }
            if (Directory.Exists(output) && Directory.EnumerateFileSystemEntries(output).Any())
            {
                throw new InvalidDataException("Graph worker requires fresh action outputs");
            }
            // Keep staging on the output volume so publication can move owned
            // trees without copying them or exporting authored inputs.
            var declaration = JsonSerializer.Deserialize<GraphContract>(File.ReadAllText(contract))
                ?? throw new InvalidDataException("Missing graph contract");
            Directory.CreateDirectory(output);
            if (request.EvaluationCacheMb is < 0 or > 4096)
            {
                throw new InvalidDataException("Evaluation cache budget must be between zero and 4096 MiB");
            }
            var reuse = request.EvaluationCacheMb > 0 && persistent && prepared != "-" && declaration.EvaluationReuseInputs is not null && ReadOnlyPackageTree.SameVolume(directory.Root, output);
            if (!reuse)
            {
                engine.Stop();
            }
            var staging = Directory.CreateDirectory(reuse ? engine.Output : Path.Combine(output, ".staging")).FullName;
            var workspace = Path.Combine(staging, "workspace");
            Directory.CreateDirectory(workspace);
            var scratch = Directory.CreateDirectory(Path.Combine(directory.Root, "request-" + Guid.NewGuid().ToString("N"))).FullName;
            try
            {
                if (request.Prepared is not null)
                {
                    var identities = inputDigests?.Where(pair => pair.Key == request.Prepared || pair.Key.StartsWith(request.Prepared + "/", StringComparison.Ordinal))
                        .OrderBy(pair => pair.Key, StringComparer.Ordinal).ToArray();
                    var identity = identities is { Length: > 0 } && identities.All(pair => pair.Value.Length != 0)
                        ? ContractFiles.Hash(identities.Select(pair => pair.Key[request.Prepared.Length..] + "=" + pair.Value))
                        : null;
                    prepared = WorkerPreparation.Materialize(prepared, preparationCache, identity);
                    if (reuse)
                    {
                        contract = engine.Prepare(contract, prepared);
                    }
                }
                foreach (var source in request.Sources)
                {
                    var path = InputPath(source.Path);
                    var destination = Path.Combine(workspace, Safe(source.Destination));
                    if (Directory.Exists(path))
                    {
                        foreach (var file in Directory.EnumerateFiles(path, "*", SearchOption.AllDirectories))
                        {
                            var relative = Path.GetRelativePath(path, file);
                            Copy(InputPath(source.Path + "/" + relative), Path.Combine(destination, Safe(relative)));
                        }
                    }
                    else
                    {
                        Copy(path, destination);
                    }
                }
                stageSeconds = requestTimer?.Elapsed.TotalSeconds ?? 0;
                var childTimer = request.ProfileBuild ? Stopwatch.StartNew() : null;
                var sdk = Path.GetDirectoryName(Environment.ProcessPath!)!;
                (int ExitCode, string Output) child;
                if (reuse)
                {
                    var result = await engine.Run(sandbox, sdk, AppContext.BaseDirectory, contract, prepared, cache, request.Target, request.ProfileBuild, request.EvaluationCacheMb);
                    child = (result.ExitCode, result.Output);
                }
                else
                {
                    var start = new ProcessStartInfo("/bin/bash") { RedirectStandardOutput = true, RedirectStandardError = true };
                    foreach (var argument in new[] { sandbox, sdk, AppContext.BaseDirectory, staging, contract, scratch, request.Target, "action", prepared, cache, prepared == "-" ? "0" : "1", request.ProfileBuild ? "1" : "0" })
                    {
                        start.ArgumentList.Add(argument);
                    }
                    child = await WorkerProcess.RunAsync(start);
                }
                childSeconds = childTimer?.Elapsed.TotalSeconds ?? 0;
                var verificationTimer = request.ProfileBuild ? Stopwatch.StartNew() : null;
                if (child.ExitCode == 0)
                {
                    foreach (var path in Directory.EnumerateFileSystemEntries(staging, "*", SearchOption.AllDirectories))
                    {
                        if (File.GetAttributes(path).HasFlag(FileAttributes.ReparsePoint))
                        {
                            throw new InvalidDataException("Graph worker output contains a link");
                        }
                    }
                }
                verificationSeconds = verificationTimer?.Elapsed.TotalSeconds ?? 0;
                if (child.ExitCode == 0)
                {
                    var publicationTimer = request.ProfileBuild ? Stopwatch.StartNew() : null;
                    GraphPublication.Publish(contract, staging, output);
                    publicationSeconds = publicationTimer?.Elapsed.TotalSeconds ?? 0;
                }
                succeeded = child.ExitCode == 0;
                return new(child.ExitCode, child.Output);
            }
            finally
            {
                var cleanupTimer = request.ProfileBuild ? Stopwatch.StartNew() : null;
                Directory.Delete(scratch, recursive: true);
                if (!succeeded)
                {
                    engine.Stop();
                }
                if (reuse)
                {
                    engine.ClearWorkspace();
                }
                else
                {
                    Directory.Delete(staging, recursive: true);
                }
                // A conservative logical-byte budget counts aliases as well as
                // blobs. Trim only between requests, with no active MSBuild.
                long bytes = 0;
                foreach (var path in Directory.EnumerateFiles(cache, "*", SearchOption.AllDirectories).Concat(Directory.EnumerateFiles(preparationCache, "*", SearchOption.AllDirectories)))
                {
                    bytes += new FileInfo(path).Length;
                    if (bytes > cacheBudget)
                    {
                        engine.Stop();
                        Directory.Delete(cache, recursive: true);
                        Directory.CreateDirectory(cache);
                        Directory.Delete(preparationCache, recursive: true);
                        Directory.CreateDirectory(preparationCache);
                        break;
                    }
                }
                if (succeeded && request.ProfileBuild)
                {
                    var reportPath = Path.Combine(output, "report.json");
                    var report = JsonNode.Parse(File.ReadAllText(reportPath)) ?? throw new InvalidDataException("Missing graph profile report");
                    report["worker"] = JsonSerializer.SerializeToNode(new
                    {
                        stagingSeconds = stageSeconds,
                        evaluationEngine = reuse ? new
                        {
                            generation = engine.Generation,
                            budgetMiB = request.EvaluationCacheMb,
                            managedBytes = engine.LastReply?.ManagedBytes,
                            residentBytes = engine.LastReply?.ResidentBytes,
                            retired = engine.LastReply?.Retire
                        } : null,
                        childSeconds,
                        outputVerificationSeconds = verificationSeconds,
                        publicationSeconds,
                        cleanupSeconds = cleanupTimer!.Elapsed.TotalSeconds,
                        totalSeconds = requestTimer!.Elapsed.TotalSeconds
                    });
                    File.WriteAllText(reportPath, report.ToJsonString());
                }
            }
        }
    }

    private static string Safe(string path)
    {
        if (Path.IsPathRooted(path) || path.Contains('\\') || path.Split('/').Any(part => part is "" or "." or ".."))
        {
            throw new InvalidDataException("Expected safe worker-relative path: " + path);
        }
        return path;
    }

    private static void Copy(string source, string destination)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
        File.Copy(source, destination, overwrite: false);
        if (!OperatingSystem.IsWindows())
        {
            File.SetUnixFileMode(destination, File.GetUnixFileMode(source));
        }
    }
}
