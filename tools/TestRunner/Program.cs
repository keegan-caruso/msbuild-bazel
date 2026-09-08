using System.Diagnostics;
using System.Security.Cryptography;
using System.Text.Json;
using System.Xml.Linq;

return await GraphTest.Run(args);

internal sealed record DataFile(string Source, string Destination, string Sha256);
internal sealed record Request(int SchemaVersion, string Project, Dictionary<string, string> GlobalProperties,
    string[] Bundles, string RuntimeDirectory, string Assembly, DataFile[] TestData, string[] ExpectedTests,
    string SdkRoot, string SourceRoot = "/_/workspace");
internal sealed record Artifact(string Path, long Size, string Sha256);

internal static class GraphTest
{
    private static readonly JsonSerializerOptions Json = new() { PropertyNameCaseInsensitive = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase, WriteIndented = true };
    private static bool Relative(string path) => path.Length > 0 && !Path.IsPathRooted(path) && !path.Contains('\\') && !path.Split('/').Any(part => part is ".." or "." or "");
    private static string Hash(string path)
    { using var stream = File.OpenRead(path); return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant(); }
    private static T Read<T>(string path) => JsonSerializer.Deserialize<T>(File.ReadAllText(path), Json)!;
    private static void Copy(string source, string target)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(target)!);
        File.Copy(source, target, false);
    }
    private static bool Properties(JsonElement saved, Dictionary<string, string> selected)
    {
        var expected = new Dictionary<string, string>(selected, StringComparer.OrdinalIgnoreCase) { ["IsGraphBuild"] = "true" };
        var actual = saved.EnumerateObject().ToDictionary(p => p.Name, p => p.Value.GetString(), StringComparer.OrdinalIgnoreCase);
        return actual.Count == expected.Count && expected.All(p => actual.TryGetValue(p.Key, out var value) && value == p.Value);
    }
    private static string Resolve(string root, string path)
    {
        if (!Relative(path)) throw new InvalidDataException("invalid declared runfile: " + path);
        return Path.Combine(root, path);
    }
    private static void WriteXml(string? path, string[] expected, bool passed, string failure)
    {
        if (string.IsNullOrEmpty(path)) return;
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var test = new XElement("testcase", new XAttribute("name", string.Join(",", expected.DefaultIfEmpty("runner"))), new XAttribute("classname", "MSBuild.VSTest"));
        if (!passed) test.Add(new XElement("failure", new XAttribute("message", "VSTest acceptance failed"), failure));
        new XDocument(new XElement("testsuites", new XElement("testsuite", new XAttribute("name", "MSBuild.VSTest"),
            new XAttribute("tests", 1), new XAttribute("failures", passed ? 0 : 1), test))).Save(path);
    }
    public static async Task<int> Run(string[] args)
    {
        var output = Environment.GetEnvironmentVariable("TEST_UNDECLARED_OUTPUTS_DIR") ?? throw new InvalidOperationException("TEST_UNDECLARED_OUTPUTS_DIR required");
        Directory.CreateDirectory(output);
        var scratchParent = Environment.GetEnvironmentVariable("TEST_TMPDIR") ?? Path.GetTempPath();
        var scratch = Path.Combine(scratchParent, "msbuild-vstest-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(scratch);
        var expected = Array.Empty<string>();
        var passed = false;
        var exitCode = -1;
        var timedOut = false;
        var total = 0;
        var successful = 0;
        var failed = 0;
        var skipped = 0;
        var command = Array.Empty<string>();
        var results = Array.Empty<object>();
        var failure = "";
        var dataHashes = new SortedDictionary<string, string>();
        var runtimeHashes = new SortedDictionary<string, string>();
        try
        {
            if (args.Length != 2 || args[0] != "--request") throw new ArgumentException("usage: dotnet TestRunner.dll --request PATH");
            if (new[] { "report.json", "results.trx", "test.log" }.Any(name => File.Exists(Path.Combine(output, name)))) throw new InvalidDataException("test output is not fresh");
            var request = Read<Request>(args[1]);
            expected = request.ExpectedTests;
            if (request.SchemaVersion != 1 || expected.Length == 0 || expected.Distinct().Count() != expected.Length ||
                !Relative(request.Project) || !Relative(request.RuntimeDirectory) || !Relative(request.Assembly) || request.Assembly.Contains('/')) throw new InvalidDataException("invalid test request");
            var runfiles = Environment.GetEnvironmentVariable("TEST_SRCDIR") ?? Directory.GetCurrentDirectory();
            var sdk = Resolve(runfiles, request.SdkRoot);
            var matches = new List<string>();
            foreach (var logical in request.Bundles)
            {
                var bundle = Resolve(runfiles, logical);
                using var seal = JsonDocument.Parse(File.ReadAllText(Path.Combine(bundle, "bundle.json")));
                if (seal.RootElement.GetProperty("schemaVersion").GetInt32() != 1 ||
                    seal.RootElement.GetProperty("resultsSha256").GetString() != Hash(Path.Combine(bundle, "results.json")) ||
                    seal.RootElement.GetProperty("artifactsSha256").GetString() != Hash(Path.Combine(bundle, "artifacts.json"))) throw new InvalidDataException("test bundle metadata corrupt");
                using var payload = JsonDocument.Parse(File.ReadAllText(Path.Combine(bundle, "results.json")));
                if (payload.RootElement.GetProperty("schemaVersion").GetInt32() != 1 || payload.RootElement.GetProperty("sdkVersion").GetString() != "10.0.400" || payload.RootElement.GetProperty("targetFramework").GetString() != "net10.0") throw new InvalidDataException("test bundle identity/version mismatch");
                if (payload.RootElement.GetProperty("project").GetString() == request.Project && Properties(payload.RootElement.GetProperty("properties"), request.GlobalProperties)) matches.Add(bundle);
            }
            if (matches.Count != 1) throw new InvalidDataException("test subject bundle missing or ambiguous");
            var subject = matches[0];
            var runtime = Path.Combine(scratch, "runtime");
            Directory.CreateDirectory(runtime);
            var artifacts = Read<Artifact[]>(Path.Combine(subject, "artifacts.json"));
            var paths = new HashSet<string>();
            foreach (var item in artifacts)
            {
                if (!Relative(item.Path) || !paths.Add(item.Path)) throw new InvalidDataException("invalid or duplicate bundle artifact");
                var source = Path.Combine(subject, "artifacts", item.Path);
                using (var stream = File.OpenRead(source))
                    if (stream.Length != item.Size || Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant() != item.Sha256) throw new InvalidDataException("test runtime artifact corrupt: " + item.Path);
                if (!item.Path.StartsWith(request.RuntimeDirectory + "/", StringComparison.Ordinal)) continue;
                var destination = item.Path[(request.RuntimeDirectory.Length + 1)..];
                Copy(source, Path.Combine(runtime, destination));
                runtimeHashes.Add(destination, item.Sha256);
            }
            if (!File.Exists(Path.Combine(runtime, request.Assembly))) throw new InvalidDataException("test assembly missing from subject runtime");
            var workspace = Path.Combine(scratch, "workspace");
            Directory.CreateDirectory(Path.Combine(workspace, Path.GetDirectoryName(request.Project)!));
            foreach (var data in request.TestData)
            {
                if (!Relative(data.Destination) || dataHashes.ContainsKey(data.Destination)) throw new InvalidDataException("invalid or duplicate test data destination");
                var source = Resolve(runfiles, data.Source);
                if (Hash(source) != data.Sha256) throw new InvalidDataException("test data hash mismatch: " + data.Destination);
                Copy(source, Path.Combine(workspace, data.Destination));
                dataHashes.Add(data.Destination, data.Sha256);
            }
            var home = Path.Combine(scratch, "home");
            var temporary = Path.Combine(scratch, "tmp");
            Directory.CreateDirectory(home);
            Directory.CreateDirectory(temporary);
            command = [Path.Combine(sdk, "dotnet"), Path.Combine(sdk, "sdk/10.0.400/vstest.console.dll"), Path.Combine(runtime, request.Assembly),
                "/TestAdapterPath:" + runtime, "/Logger:trx;LogFileName=results.trx", "/ResultsDirectory:" + output];
            var info = new ProcessStartInfo(command[0]) { WorkingDirectory = workspace, UseShellExecute = false, RedirectStandardOutput = true, RedirectStandardError = true };
            foreach (var arg in command.Skip(1)) info.ArgumentList.Add(arg);
            info.Environment.Clear();
            foreach (var pair in new Dictionary<string, string>
            {
                ["PATH"] = "/usr/bin:/bin",
                ["LANG"] = "en_US.UTF-8",
                ["HOME"] = home,
                ["DOTNET_ROOT"] = sdk,
                ["DOTNET_CLI_HOME"] = home,
                ["DOTNET_MULTILEVEL_LOOKUP"] = "0",
                ["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1",
                ["MSBUILDDISABLENODEREUSE"] = "1",
                ["TMPDIR"] = temporary,
                ["CI"] = "true",
                ["DiffEngine_Disabled"] = "true",
                ["SHOULDLY_SOURCE_PATH_MAP"] = workspace + "=" + request.SourceRoot
            }) info.Environment[pair.Key] = pair.Value;
            Console.WriteLine("RULES_MSBUILD_VSTEST_START:" + request.Project);
            using var process = Process.Start(info) ?? throw new InvalidOperationException("VSTest failed to start");
            var stdout = process.StandardOutput.ReadToEndAsync();
            var stderr = process.StandardError.ReadToEndAsync();
            using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(3));
            try { await process.WaitForExitAsync(timeout.Token); }
            catch (OperationCanceledException) { timedOut = true; process.Kill(entireProcessTree: true); await process.WaitForExitAsync(); }
            exitCode = process.ExitCode;
            var log = await stdout + await stderr;
            File.WriteAllText(Path.Combine(output, "test.log"), log);
            Console.Write(log);
            var trxPath = Path.Combine(output, "results.trx");
            if (!File.Exists(trxPath)) throw new InvalidDataException("VSTest did not publish TRX");
            var trx = XDocument.Load(trxPath);
            var counters = trx.Descendants().Single(e => e.Name.LocalName == "Counters");
            total = int.Parse(counters.Attribute("total")!.Value);
            successful = int.Parse(counters.Attribute("passed")!.Value);
            failed = int.Parse(counters.Attribute("failed")!.Value);
            skipped = total - successful - failed;
            var actual = trx.Descendants().Where(e => e.Name.LocalName == "UnitTestResult").ToArray();
            results = actual.Select(e => (object)new { name = e.Attribute("testName")?.Value, outcome = e.Attribute("outcome")?.Value }).ToArray();
            passed = !timedOut && exitCode == 0 && total == expected.Length && successful == expected.Length && failed == 0 && skipped == 0 &&
                actual.Length == expected.Length && actual.Select(e => e.Attribute("testName")!.Value).Order().SequenceEqual(expected.Order()) &&
                actual.All(e => e.Attribute("outcome")?.Value == "Passed");
            if (!passed) failure = "VSTest exit/count/name/outcome acceptance failed";
            foreach (var received in Directory.EnumerateFiles(workspace, "*.received.*", SearchOption.AllDirectories))
                Copy(received, Path.Combine(output, "received", Path.GetRelativePath(workspace, received)));
        }
        catch (Exception error) { failure = error.ToString(); Console.Error.WriteLine(failure); }
        finally
        {
            File.WriteAllText(Path.Combine(output, "report.json"), JsonSerializer.Serialize(new
            {
                schemaVersion = 1,
                passed,
                exitCode,
                runnerExitCode = passed ? 0 : 1,
                timedOut,
                total,
                successful,
                failed,
                skipped,
                expectedTests = expected,
                tests = results,
                command,
                dataHashes,
                runtimeHashes,
                failure,
                buildOrRestoreInvoked = false,
                trx = File.Exists(Path.Combine(output, "results.trx")) ? "results.trx" : null
            }, Json));
            WriteXml(Environment.GetEnvironmentVariable("XML_OUTPUT_FILE"), expected, passed, failure);
            Directory.Delete(scratch, recursive: true);
        }
        return passed ? 0 : 1;
    }
}
