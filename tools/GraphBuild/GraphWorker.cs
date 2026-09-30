using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace RulesMSBuild.GraphBuild;

// Persistent transport/cache broker, not a persistent MSBuild engine. Every
// request gets a fresh workspace and a fresh process in the stable-path sandbox.
internal static class GraphWorker
{
    private sealed record Input(string Path, string Digest = "");
    private sealed record WorkRequest(string[] Arguments, Input[] Inputs, int RequestId = 0, bool Cancel = false);
    private sealed record Reply(int ExitCode, string Output, int RequestId = 0);
    private sealed record Source(string Path, string Destination);
    private sealed record Request(string Contract, string Output, string Target, string? Prepared, Source[] Sources, bool ProfileBuild = false);
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
            var workspace = Path.Combine(output, "workspace");
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
                var start = new ProcessStartInfo("/bin/bash") { RedirectStandardOutput = true, RedirectStandardError = true };
                foreach (var argument in new[] { sandbox, sdk, AppContext.BaseDirectory, output, contract, scratch, request.Target, "action", prepared, cache, prepared == "-" ? "0" : "1", request.ProfileBuild ? "1" : "0" })
                {
                    start.ArgumentList.Add(argument);
                }
                using var child = Process.Start(start) ?? throw new IOException("Cannot start graph sandbox");
                var stdout = child.StandardOutput.ReadToEndAsync();
                var stderr = child.StandardError.ReadToEndAsync();
                await child.WaitForExitAsync();
                var log = await stdout + await stderr;
                childSeconds = childTimer?.Elapsed.TotalSeconds ?? 0;
                var verificationTimer = request.ProfileBuild ? Stopwatch.StartNew() : null;
                if (child.ExitCode == 0)
                {
                    foreach (var path in Directory.EnumerateFileSystemEntries(output, "*", SearchOption.AllDirectories))
                    {
                        if (File.GetAttributes(path).HasFlag(FileAttributes.ReparsePoint))
                        {
                            throw new InvalidDataException("Graph worker output contains a link");
                        }
                    }
                }
                verificationSeconds = verificationTimer?.Elapsed.TotalSeconds ?? 0;
                succeeded = child.ExitCode == 0;
                return new(child.ExitCode, log);
            }
            finally
            {
                var cleanupTimer = request.ProfileBuild ? Stopwatch.StartNew() : null;
                Directory.Delete(scratch, recursive: true);
                // A conservative logical-byte budget counts aliases as well as
                // blobs. Trim only between requests, with no active MSBuild.
                long bytes = 0;
                foreach (var path in Directory.EnumerateFiles(cache, "*", SearchOption.AllDirectories).Concat(Directory.EnumerateFiles(preparationCache, "*", SearchOption.AllDirectories)))
                {
                    bytes += new FileInfo(path).Length;
                    if (bytes > cacheBudget)
                    {
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
                        childSeconds,
                        outputVerificationSeconds = verificationSeconds,
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
