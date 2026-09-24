using System.Diagnostics;
using System.Text.Json;

internal static class Program
{
    internal static readonly JsonSerializerOptions Json = new() { PropertyNameCaseInsensitive = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true };
    internal static string ReadPath(string value) => Path.GetFullPath(value);
    internal static string Real(string value)
    {
        var full = Path.GetFullPath(value);
        var current = Path.GetPathRoot(full)!;
        foreach (var part in full[current.Length..].Split(Path.DirectorySeparatorChar, StringSplitOptions.RemoveEmptyEntries))
        {
            current = Path.Combine(current, part);
            var info = new FileInfo(current);
            if (info.LinkTarget is not null)
            {
                current = info.ResolveLinkTarget(true)!.FullName;
            }
        }
        return current;
    }
    private static T Read<T>(string path) => JsonSerializer.Deserialize<T>(File.ReadAllText(path), Json)!;
    internal static string Safe(string value)
    {
        if (string.IsNullOrEmpty(value) || Path.IsPathRooted(value) || value.Contains('\\') || value.Split('/').Any(p => p is "" or "." or "..") || value.IndexOfAny(['\0', '\r', '\n']) >= 0)
        {
            throw new InvalidDataException("Unsafe logical path: " + value);
        }

        return value;
    }
    internal static string Escape(string value) => value.Replace("%", "%25", StringComparison.Ordinal).Replace("$", "%24", StringComparison.Ordinal).Replace("@", "%40", StringComparison.Ordinal).Replace(";", "%3B", StringComparison.Ordinal).Replace("'", "%27", StringComparison.Ordinal).Replace("(", "%28", StringComparison.Ordinal).Replace(")", "%29", StringComparison.Ordinal).Replace("*", "%2A", StringComparison.Ordinal).Replace("?", "%3F", StringComparison.Ordinal);
    internal static void Copy(string source, string target)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        if (File.Exists(target))
        {
            if (!File.ReadAllBytes(source).AsSpan().SequenceEqual(File.ReadAllBytes(target)))
            {
                throw new InvalidDataException("Conflicting runtime/input destination: " + target);
            }

            return;
        }
        File.Copy(source, target);
    }
    public static int Main(string[] args)
    {
        try
        {
            if (args is ["--bazel-worker", var toolInputs, "--persistent_worker"] && toolInputs.StartsWith("--tool-inputs=", StringComparison.Ordinal))
            {
                return LinuxWorker.Run(toolInputs["--tool-inputs=".Length..]).GetAwaiter().GetResult();
            }

            if (args is ["--bazel-worker", var toolArgument, var responseFile] && toolArgument.StartsWith("--tool-inputs=", StringComparison.Ordinal) && responseFile.StartsWith('@'))
            {
                return Build(Read<Request>(File.ReadAllText(responseFile[1..]).Trim()));
            }

            if (args is ["--bazel-worker", "--persistent_worker"])
            {
                return LinuxWorker.Run().GetAwaiter().GetResult();
            }

            if (args is ["--isolated-worker"])
            {
                return LinuxWorker.Child().GetAwaiter().GetResult();
            }

            if (args is ["--bazel-worker", var parameter] && parameter.StartsWith('@'))
            {
                return Build(Read<Request>(File.ReadAllText(parameter[1..]).Trim()));
            }

            if (args is ["pair", var pair])
            {
                AssemblyContracts.Pair(Read<AssemblyPair>(pair));
                return 0;
            }
            if (args is ["layout", var layout])
            {
                ArtifactLayouts.Compose(Read<LayoutRequest>(layout));
                return 0;
            }
            if (args is ["extract", var extraction])
            {
                Package.Extract(Read<PackageRequest>(extraction));
                return 0;
            }
            if (args is ["build", var request])
            {
                return Build(Read<Request>(request));
            }

            if (args is ["compile", var session])
            {
                return ProjectCompilation.Compile(Read<Session>(session));
            }

            if (args.Length >= 2 && args[0] == "run")
            {
                return ApplicationLaunch.Run(Read<Launch>(args[1]), args[2..]);
            }

            throw new ArgumentException("Expected build/compile/run request.json");
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
    private static int Build(Request r)
    {
        Safe(r.Assembly);
        if (r.Assembly.Contains('/'))
        {
            throw new InvalidDataException("Assembly name must be a filename");
        }

        var diagnostics = ReadPath(r.Diagnostics);
        Directory.CreateDirectory(diagnostics);
        diagnostics = Real(diagnostics);
        var work = Path.Combine(diagnostics, ".work");
        var workspace = Path.Combine(work, "workspace");
        var state = Path.Combine(work, "state");
        Directory.CreateDirectory(workspace);
        Directory.CreateDirectory(state);
        try
        {
            var session = BuildPreparation.Prepare(r, workspace, state);
            var sdk = session.Sdk;
            var sessionPath = Path.Combine(state, "session.json");
            File.WriteAllText(sessionPath, JsonSerializer.Serialize(session, Json));
            var roots = Read<string[]>(r.RuntimeManifest);
            var start = Sandbox.Start(workspace, state, roots.Append(sdk).Append(session.ToolRoot).Concat(r.Packages.Select(p => Real(p.Directory))), sdk);
            start.ArgumentList.Add(Path.Combine(sdk, "dotnet"));
            start.ArgumentList.Add(Path.Combine(session.ToolRoot, "ExplicitBuild.dll"));
            start.ArgumentList.Add("compile");
            start.ArgumentList.Add(sessionPath);
            var exit = Execute(start, Path.Combine(diagnostics, "build.log"));
            if (exit != 0)
            {
                return exit;
            }

            BuildOutputs.Publish(r, state);
            return 0;
        }
        finally
        {
            if (Directory.Exists(work))
            {
                Directory.Delete(work, true);
            }
        }
    }
    private static int Execute(ProcessStartInfo start, string? log = null)
    {
        start.RedirectStandardOutput = true;
        start.RedirectStandardError = true;
        using var process = Process.Start(start)!;
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();
        process.WaitForExit();
        Task.WaitAll(stdout, stderr);
        if (log is not null)
        {
            File.WriteAllText(log, stdout.Result + stderr.Result);
        }

        Console.Write(stdout.Result);
        Console.Error.Write(stderr.Result);
        return process.ExitCode;
    }
}
