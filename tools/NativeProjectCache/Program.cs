using System.Diagnostics;
using System.Text.Json;
using System.Xml.Linq;
using ActionRunner;
using NativeCache;

internal sealed record RunnerFile(string Source, string Destination);
internal sealed record RunnerRequest(string Entry, string Output, string Diagnostics, string Manifest, string Restore, RunnerFile[] Sources, RunnerFile[] Seeds, string? ReadProbe = null, string? NetworkProbe = null, string? WriteProbe = null, string? PreparedPlan = null);
internal sealed record PortableManifest(string Toolchain, Dictionary<string, DeclaredProject> Projects, string Policy = "native-qualified-v2");

internal static class Program
{
    private static readonly JsonSerializerOptions Json = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true };
    public static async Task<int> Main(string[] args)
    {
        string? scratch = null;
        string? diagnosticsPath = null;
        var phases = new Dictionary<string, double>();
        var timer = Stopwatch.StartNew();
        void Mark(string name) { phases[name] = timer.Elapsed.TotalSeconds; timer.Restart(); }
        try
        {
            if (args is not ["--portable-request", var file]) throw new ArgumentException("expected --portable-request PATH");
            var request = JsonSerializer.Deserialize<RunnerRequest>(File.ReadAllText(file), Json)!;
            if (request.PreparedPlan is not null)
            {
                if (request.Sources.Length != 0) throw new InvalidDataException("Prepared plan cannot also supply explicit sources");
                var planSources = Path.Combine(request.PreparedPlan, "src");
                request = request with { Sources = Directory.EnumerateFiles(planSources, "*", SearchOption.AllDirectories).Select(path => new RunnerFile(path, Path.GetRelativePath(planSources, path))).ToArray() };
            }
            var output = Path.GetFullPath(request.Output);
            var diagnostics = Path.GetFullPath(request.Diagnostics);
            diagnosticsPath = diagnostics;
            if (Directory.Exists(output) && Directory.EnumerateFileSystemEntries(output).Any())
                throw new InvalidDataException("portable runner requires an empty output");
            scratch = Path.Combine(output, ".work");
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
            Mark("sourceAndRestore");
            foreach (var input in request.Seeds)
            {
                if (!Files.ValidRelativePath(input.Destination)) throw new InvalidDataException("invalid seed path");
                Files.Copy(input.Source, Path.Combine(cache, input.Destination));
            }
            Mark("seedCopy");
            var manifest = JsonSerializer.Deserialize<PortableManifest>(File.ReadAllText(request.Manifest), Json)!;
            var selection = "";
            if (manifest.Policy == "evaluated-api-runtime-v2")
            {
                var document = new XElement("Project");
                foreach (var (project, declared) in manifest.Projects)
                {
                    if (!Files.ValidRelativePath(project)) throw new InvalidDataException("invalid declared project");
                    var full = Path.Combine(workspace, project);
                    var condition = "'$(MSBuildProjectFullPath)' == '" + full.Replace("'", "%27", StringComparison.Ordinal) + "'";
                    document.Add(new XElement("PropertyGroup", new XAttribute("Condition", condition),
                        new XElement("InnerBuildProperty", ""), new XElement("InnerBuildPropertyValues", "")));
                    var items = new XElement("ItemGroup", new XAttribute("Condition", condition));
                    foreach (var dependency in declared.Dependencies)
                    {
                        if (!manifest.Projects.ContainsKey(dependency)) throw new InvalidDataException("missing declared reference");
                        items.Add(new XElement("ProjectReference", new XAttribute("Update", Path.GetRelativePath(Path.GetDirectoryName(full)!, Path.Combine(workspace, dependency))),
                            new XElement("SetTargetFramework", "TargetFramework=net10.0")));
                    }
                    document.Add(items);
                }
                var path = Path.Combine(scratch, "selected.targets");
                new XDocument(document).Save(path);
                selection = "<PropertyGroup><AfterMicrosoftNETSdkTargets>$(AfterMicrosoftNETSdkTargets);" + System.Security.SecurityElement.Escape(path) + "</AfterMicrosoftNETSdkTargets></PropertyGroup>";
            }
            var plugin = typeof(Program).Assembly.Location;
            var targets = Path.Combine(scratch, "Cache.targets");
            File.WriteAllText(targets, "<Project><PropertyGroup><_NativeOriginalTargets>$([MSBuild]::GetPathOfFileAbove('Directory.Build.targets', '$(MSBuildProjectDirectory)/'))</_NativeOriginalTargets></PropertyGroup>" +
                "<Import Project=\"$(_NativeOriginalTargets)\" Condition=\"'$(_NativeOriginalTargets)' != ''\" />" +
                selection + "<ItemGroup><ProjectCachePlugin Include=\"" + System.Security.SecurityElement.Escape(plugin) + "\" /></ItemGroup></Project>");
            var files = Directory.EnumerateFiles(workspace, "*", SearchOption.AllDirectories).Select(path => new DeclaredFile(Path.GetRelativePath(workspace, path), Files.Hash(path))).ToArray();
            var sessionPath = Path.Combine(scratch, "session.json");
            var pending = Path.Combine(scratch, "pending"); Directory.CreateDirectory(pending);
            var report = Path.Combine(diagnostics, "events.json");
            var session = new Session(workspace, cache, pending, report, request.Entry, manifest.Toolchain, files, manifest.Projects, TargetsPath: targets, Policy: manifest.Policy);
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
            if (manifest.Policy == "evaluated-api-runtime-v2") start.Environment["MSBuildEnableWorkloadResolver"] = "false";
            // Failed builds must not leave diagnostic FIFOs for Bazel to hash.
            start.Environment["DOTNET_EnableDiagnostics"] = "0";
            start.Environment["NATIVE_CACHE_SESSION"] = sessionPath;
            Mark("sessionSetup");
            using var process = Process.Start(start)!;
            var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
            try { await process.WaitForExitAsync().WaitAsync(TimeSpan.FromMinutes(10)); }
            catch { process.Kill(true); throw; }
            var log = await stdout + await stderr;
            Mark("msbuild");
            File.WriteAllText(Path.Combine(diagnostics, "build.log"), log);
            var compiles = log.Split('\n').Count(line => line.Contains("/Roslyn/bincore/csc", StringComparison.Ordinal) && line.Contains(" /noconfig ", StringComparison.Ordinal));
            File.WriteAllText(Path.Combine(diagnostics, "action.json"), JsonSerializer.Serialize(new { compiles, exitCode = process.ExitCode, environmentPolicy = manifest.Policy == "evaluated-api-runtime-v2" ? "evaluated-net10-release-env-v1" : PortableEnvironment.Policy }, Json));
            if (process.ExitCode != 0) { Console.Error.WriteLine(log); return process.ExitCode; }
            // Export only bundles selected by this graph, never an accumulating history.
            var selected = JsonSerializer.Deserialize<JsonElement[]>(File.ReadAllText(report))!
                .Where(e => e.GetProperty("kind").GetString() is "hit" or "miss")
                .Select(e => e.GetProperty("key").GetString()!).ToHashSet(StringComparer.Ordinal);
            foreach (var directory in Directory.EnumerateDirectories(cache))
                if (!selected.Contains(Path.GetFileName(directory))) Directory.Delete(directory, true);
            Mark("selectBundles");
            // Compile cache bundles can contain historical copy-local implementations.
            // Publish a separate sealed current runtime for test consumers.
            var entryBundle = Directory.EnumerateDirectories(cache).Single(bundle =>
                JsonSerializer.Deserialize<Results>(File.ReadAllText(Path.Combine(bundle, "results.json")), Json)!.Project == request.Entry);
            var entryArtifacts = CompileBoundary.Validate(entryBundle);
            var runtime = Path.Combine(output, "runtime", Path.GetFileName(entryBundle));
            Mark("validateEntry");
            var runtimeDirectory = Path.Combine(Path.GetDirectoryName(request.Entry)!, "bin/Release/net10.0");
            // Keep reference/intermediate artifacts, but never copy the historical
            // runtime that current composition is about to replace. Validation
            // above still covers every cached artifact, including that runtime.
            foreach (var artifact in entryArtifacts)
                if (!artifact.Path.StartsWith(runtimeDirectory + "/", StringComparison.Ordinal))
                    Files.Copy(Path.Combine(entryBundle, "artifacts", artifact.Path), Path.Combine(runtime, "artifacts", artifact.Path));
            Files.Copy(Path.Combine(entryBundle, "results.json"), Path.Combine(runtime, "results.json"));
            var destination = Path.Combine(runtime, "artifacts", runtimeDirectory);
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            // MSBuild has exited and all graph cache bundles are published. This
            // private scratch tree is no longer consumed; both paths are inside
            // the same output tree. Move ownership rather than copy then delete.
            Directory.Move(Path.Combine(workspace, runtimeDirectory), destination);
            Mark("runtimeCopy");
            CompileBoundary.Seal(runtime);
            Mark("runtimeSeal");
            Files.CopyTree(Path.Combine(runtime, "artifacts", runtimeDirectory), Path.Combine(output, "app"));
            Mark("appCopy");
            Directory.Delete(scratch, true);
            Mark("cleanup");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        finally
        {
            if (scratch is not null && Directory.Exists(scratch)) Directory.Delete(scratch, true);
            if (diagnosticsPath is not null && Directory.Exists(diagnosticsPath))
                File.WriteAllText(Path.Combine(diagnosticsPath, "timings.json"), JsonSerializer.Serialize(phases, Json));
        }
    }
}
