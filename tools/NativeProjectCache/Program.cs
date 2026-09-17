using System.Diagnostics;
using System.Text.Json;
using ActionRunner;
using NativeCache;

internal sealed record RunnerFile(string Source, string Destination);
internal sealed record RunnerRequest(string Entry, string Output, string Diagnostics, string Manifest, string Restore, RunnerFile[] Sources, RunnerFile[] Seeds, string? ReadProbe = null, string? NetworkProbe = null, string? WriteProbe = null);
internal sealed record PortableManifest(string Toolchain, Dictionary<string, DeclaredProject> Projects);

internal static class Program
{
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true };
    public static async Task<int> Main(string[] args)
    {
        try
        {
            if (args is not ["--portable-request", var file]) throw new ArgumentException("expected --portable-request PATH");
            var request = JsonSerializer.Deserialize<RunnerRequest>(File.ReadAllText(file), Json)!;
            var output = Path.GetFullPath(request.Output);
            var diagnostics = Path.GetFullPath(request.Diagnostics);
            if (Directory.Exists(output) && Directory.EnumerateFileSystemEntries(output).Any())
                throw new InvalidDataException("portable runner requires an empty output");
            var scratch = Path.Combine(output, ".work");
            var workspace = Path.Combine(scratch, "w");
            var home = Path.Combine(scratch, "home"); Directory.CreateDirectory(home);
            Directory.CreateDirectory(workspace); Directory.CreateDirectory(diagnostics);
            var cache = Path.Combine(output, "cache"); Directory.CreateDirectory(cache);
            var sdk = Path.GetDirectoryName(Environment.ProcessPath!)!;
            foreach (var input in request.Sources)
            {
                if (!Files.ValidRelativePath(input.Destination)) throw new InvalidDataException("invalid source path");
                Files.Copy(input.Source, Path.Combine(workspace, input.Destination));
            }
            foreach (var (relative, contents) in JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(request.Restore))!)
            {
                if (!Files.ValidRelativePath(relative)) throw new InvalidDataException("invalid restore path");
                var path = Path.Combine(workspace, relative); Directory.CreateDirectory(Path.GetDirectoryName(path)!);
                File.WriteAllText(path, contents.Replace("${WORKSPACE}", workspace, StringComparison.Ordinal).Replace("${SDK}", sdk, StringComparison.Ordinal).Replace("${HOME}", home, StringComparison.Ordinal));
            }
            foreach (var input in request.Seeds)
            {
                if (!Files.ValidRelativePath(input.Destination)) throw new InvalidDataException("invalid seed path");
                Files.Copy(input.Source, Path.Combine(cache, input.Destination));
            }
            var manifest = JsonSerializer.Deserialize<PortableManifest>(File.ReadAllText(request.Manifest), Json)!;
            var plugin = typeof(Program).Assembly.Location;
            var targets = Path.Combine(scratch, "Cache.targets");
            File.WriteAllText(targets, "<Project><ItemGroup><ProjectCachePlugin Include=\"" + System.Security.SecurityElement.Escape(plugin) + "\" /></ItemGroup></Project>");
            var files = Directory.EnumerateFiles(workspace, "*", SearchOption.AllDirectories).Select(path => new DeclaredFile(Path.GetRelativePath(workspace, path), Files.Hash(path))).ToArray();
            var sessionPath = Path.Combine(scratch, "session.json");
            var pending = Path.Combine(scratch, "pending"); Directory.CreateDirectory(pending);
            var report = Path.Combine(diagnostics, "events.json");
            var session = new Session(workspace, cache, pending, report, request.Entry, manifest.Toolchain, files, manifest.Projects, TargetsPath: targets);
            File.WriteAllText(sessionPath, JsonSerializer.Serialize(session, Json));
            if (request.ReadProbe is not null) File.ReadAllText(request.ReadProbe);
            if (request.WriteProbe is not null) File.WriteAllText(request.WriteProbe, "unexpected write");
            if (request.NetworkProbe is not null)
            {
                using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(3) };
                using var response = await client.GetAsync(request.NetworkProbe);
            }
            var start = new ProcessStartInfo(Path.Combine(sdk, "dotnet")) { WorkingDirectory = workspace, RedirectStandardOutput = true, RedirectStandardError = true };
            foreach (var arg in new[] { "exec", Path.Combine(sdk, "sdk/10.0.400/MSBuild.dll"), request.Entry, "-t:Build", "-p:Configuration=Release", "-p:TargetFramework=net10.0", "-graphBuild", "-isolateProjects", "-m:2", "-nodeReuse:false", "-nologo", "-verbosity:normal", "-p:PathMap=" + workspace + "=/_/workspace", "-p:DirectoryBuildTargetsPath=" + targets }) start.ArgumentList.Add(arg);
            start.Environment.Clear();
            foreach (var (key, value) in PortableEnvironment.Create(sdk, home, scratch, workspace)) start.Environment[key] = value;
            start.Environment["NATIVE_CACHE_SESSION"] = sessionPath;
            using var process = Process.Start(start)!;
            var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
            try { await process.WaitForExitAsync().WaitAsync(TimeSpan.FromMinutes(10)); }
            catch { process.Kill(true); throw; }
            var log = await stdout + await stderr;
            File.WriteAllText(Path.Combine(diagnostics, "build.log"), log);
            var compiles = log.Split('\n').Count(line => line.Contains("/Roslyn/bincore/csc", StringComparison.Ordinal) && line.Contains(" /noconfig ", StringComparison.Ordinal));
            File.WriteAllText(Path.Combine(diagnostics, "action.json"), JsonSerializer.Serialize(new { compiles, exitCode = process.ExitCode, environmentPolicy = PortableEnvironment.Policy }, Json));
            if (process.ExitCode != 0) { Console.Error.WriteLine(log); return process.ExitCode; }
            // Export only bundles selected by this graph, never an accumulating history.
            var selected = JsonSerializer.Deserialize<JsonElement[]>(File.ReadAllText(report))!
                .Where(e => e.GetProperty("kind").GetString() is "hit" or "miss")
                .Select(e => e.GetProperty("key").GetString()!).ToHashSet(StringComparer.Ordinal);
            foreach (var directory in Directory.EnumerateDirectories(cache))
                if (!selected.Contains(Path.GetFileName(directory))) Directory.Delete(directory, true);
            Files.CopyTree(Path.Combine(workspace, Path.GetDirectoryName(request.Entry)!, "bin/Release/net10.0"), Path.Combine(output, "app"));
            Directory.Delete(scratch, true);
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
