using System.Diagnostics;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace RulesMSBuild.Preparation;

internal static class LockedRestore
{
    internal static string SourceReadDeny(string workspace, IEnumerable<string> bodies)
    {
        // Match the Starlark body classifier without thousands of literal rules:
        // macOS's sandbox compiler cannot serialize a large per-file deny list.
        foreach (var body in bodies)
        {
            Host.Safe(body);
            if (!body.EndsWith(".cs", StringComparison.Ordinal) || body.StartsWith(".nuget/", StringComparison.Ordinal) || body.Contains("/obj/", StringComparison.Ordinal))
                throw new InvalidDataException("Invalid locked restore source-body declaration");
        }
        return "(deny file-read-data (require-all (subpath " + Json.Canonical(JsonValue.Create(workspace)) +
            ") (regex #\"[.]cs$\") (require-not (subpath " + Json.Canonical(JsonValue.Create(Path.Combine(workspace, ".nuget"))) +
            ")) (require-not (regex " + Json.Canonical(JsonValue.Create("^" + Regex.Escape(workspace) + "/.*/obj/")) + "))))";
    }

    public static JsonObject Describe(string workspace, IEnumerable<string> projects)
    {
        var packages = new JsonObject();
        foreach (var project in projects)
        {
            var path = Path.Combine(workspace, Path.GetDirectoryName(Host.Safe(project))!, "packages.lock.json");
            var document = Json.Read(path);
            if (document["version"]?.GetValue<int>() is not (1 or 2)) throw new InvalidDataException("Unsupported NuGet lock version");
            foreach (var framework in document["dependencies"]!.AsObject())
                foreach (var (id, item) in framework.Value!.AsObject())
                {
                    var type = item!.String("type");
                    if (type.Equals("Project", StringComparison.OrdinalIgnoreCase)) continue;
                    if (type is not ("Direct" or "Transitive" or "CentralTransitive")) throw new InvalidDataException("Unsupported NuGet lock dependency type");
                    var key = Host.Safe((id + "/" + item.String("resolved")).ToLowerInvariant());
                    var hash = item.String("contentHash");
                    if (key.Split('/').Length != 2 || Convert.FromBase64String(hash).Length != 64) throw new InvalidDataException("Invalid NuGet lock identity");
                    if (packages[key] is { } previous && previous.GetValue<string>() != hash) throw new InvalidDataException("Conflicting NuGet lock hashes");
                    packages[key] = hash;
                }
        }
        return new JsonObject { ["staged"] = false, ["packages"] = packages.Count, ["bytes"] = 0, ["copied"] = false, ["locked"] = packages };
    }

    public static void Run(JsonNode request)
    {
        var diagnostics = Path.GetFullPath(request.String("diagnostics")); Directory.CreateDirectory(diagnostics);
        var scratch = Path.Combine(diagnostics, ".work"); var workspace = Path.Combine(scratch, "workspace");
        var packages = Path.Combine(workspace, ".nuget/packages");
        var home = Path.Combine(scratch, "home"); var temp = Path.Combine(scratch, "tmp");
        Directory.CreateDirectory(packages); Directory.CreateDirectory(home); Directory.CreateDirectory(temp);
        // This is a new private cache, so no legacy NuGet data needs migration.
        // The sentinel avoids NuGet's machine-wide /tmp migration mutex.
        var data = Path.Combine(home, "data"); var migrations = Path.Combine(data, "NuGet/Migrations");
        Directory.CreateDirectory(migrations); File.WriteAllText(Path.Combine(migrations, "1"), "");
        var clock = Stopwatch.StartNew();
        try
        {
            foreach (var input in request.Array("sources"))
            {
                var target = Path.Combine(workspace, Host.Safe(input!.String("destination")));
                Host.Copy(input.String("source"), target); FileTree.SetMode(target, FileTree.Mode(target) | UnixFileMode.UserWrite);
            }
            var bodies = request.Array("sourceNames").Select(item => Host.Safe(item!.GetValue<string>())).ToArray();
            foreach (var name in bodies)
            {
                var path = Path.Combine(workspace, name); Directory.CreateDirectory(Path.GetDirectoryName(path)!); File.WriteAllBytes(path, []);
            }
            var projects = request.Array("projects").Select(item => Host.Safe(item!.GetValue<string>())).ToArray();
            Describe(workspace, projects);
            var before = FileTree.Files(workspace).ToDictionary(path => path, path => FileTree.HashRegular(path).Digest, StringComparer.Ordinal);
            var sdk = Host.Real(Path.GetDirectoryName(Environment.ProcessPath!)!);
            var runtime = Json.Read(request.String("runtimeManifest")).AsArray().Select(item => item!.GetValue<string>());
            var profile = Discovery.Profile(runtime.Append(scratch), scratch) + "\n" + SourceReadDeny(workspace, bodies);
            var sandbox = Path.Combine(scratch, "sandbox.sb"); File.WriteAllText(sandbox, profile);
            var start = new ProcessStartInfo("/usr/bin/sandbox-exec") { WorkingDirectory = workspace, RedirectStandardOutput = true, RedirectStandardError = true };
            // Restore each project's authored frameworks. A global TargetFramework
            // incorrectly forces analyzer projects (for example netstandard2.0)
            // to the application framework; discovery selects build nodes later.
            foreach (var argument in new[] { "-f", sandbox, Path.Combine(sdk, "dotnet"), "exec", Path.Combine(sdk, "sdk/10.0.400/MSBuild.dll"), Host.Safe(request.String("entry")), "-t:Restore", "-p:Configuration=Release", "-p:RestorePackagesWithLockFile=true", "-p:RestoreLockedMode=true", "-p:NuGetAudit=false", "-p:RestorePackagesPath=" + packages, "-p:RestoreConfigFile=" + Path.Combine(workspace, Host.Safe(request.String("config"))), "-nodeReuse:false", "-m:1", "-nologo", "-verbosity:minimal" }) start.ArgumentList.Add(argument);
            start.Environment.Clear();
            foreach (var (key, value) in new Dictionary<string, string>
            {
                ["PATH"] = sdk,
                ["HOME"] = home,
                ["XDG_DATA_HOME"] = data,
                ["DOTNET_ROOT"] = sdk,
                ["DOTNET_HOST_PATH"] = Path.Combine(sdk, "dotnet"),
                ["DOTNET_CLI_HOME"] = home,
                ["NUGET_PACKAGES"] = packages,
                ["NUGET_HTTP_CACHE_PATH"] = Path.Combine(scratch, "http"),
                ["NUGET_SCRATCH"] = Path.Combine(scratch, "nuget-scratch"),
                ["TMPDIR"] = temp,
                ["LANG"] = "en_US.UTF-8",
                ["LC_ALL"] = "en_US.UTF-8",
                ["TZ"] = "UTC",
                ["MSBuildEnableWorkloadResolver"] = "false",
                ["MSBUILDDISABLENODEREUSE"] = "1",
                ["DOTNET_EnableDiagnostics"] = "0",
                ["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1",
                ["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1",
                ["DOTNET_MULTILEVEL_LOOKUP"] = "0"
            }) start.Environment[key] = value;
            using var process = Process.Start(start)!;
            var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
            if (!process.WaitForExit(180000)) { process.Kill(true); throw new InvalidDataException("Locked restore timed out"); }
            Task.WaitAll(stdout, stderr); var log = stdout.Result + stderr.Result;
            File.WriteAllText(Path.Combine(diagnostics, "restore.log"), log);
            if (process.ExitCode != 0) throw new InvalidDataException("Sandboxed locked restore failed: " + log);
            foreach (var (path, hash) in before) if (FileTree.HashRegular(path).Digest != hash) throw new InvalidDataException("Restore modified a declared input: " + Path.GetRelativePath(workspace, path));
            var outputs = request.Array("outputs").ToDictionary(item => Host.Safe(item!.String("name")), item => item!.String("output"), StringComparer.Ordinal);
            var generated = FileTree.Files(workspace).Where(path => !before.ContainsKey(path)).Select(path => Path.GetRelativePath(workspace, path)).ToHashSet(StringComparer.Ordinal);
            if (!generated.SetEquals(outputs.Keys)) throw new InvalidDataException("Restore outputs differ from the declared project layout: " + string.Join(",", generated.Except(outputs.Keys).Concat(outputs.Keys.Except(generated))));
            foreach (var (name, destination) in outputs)
            {
                Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
                File.WriteAllText(destination, RestoreInputs.Normalize(File.ReadAllText(Path.Combine(workspace, name)), workspace, packages, name));
            }
            Json.Write(Path.Combine(diagnostics, "report.json"), new JsonObject { ["accepted"] = true, ["projects"] = projects.Length, ["seconds"] = clock.Elapsed.TotalSeconds, ["network"] = "denied", ["sourceBodyReads"] = "denied", ["locked"] = true });
        }
        finally { FileTree.Remove(scratch); }
    }
}
