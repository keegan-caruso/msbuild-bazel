using System.Diagnostics;
using System.Text.Json.Nodes;

namespace RulesMSBuild.Preparation;

internal sealed class Discovery
{
    public const string Policy = "dotnet-native-discovery-v1";
    private readonly string root;
    private readonly string sdk;
    private readonly string workspace;
    private readonly string directory;
    private readonly string output;
    private readonly string[] runtimes;
    private readonly Dictionary<string, string> roots = new(StringComparer.Ordinal);
    private readonly Dictionary<string, JsonObject> identities = new(StringComparer.Ordinal);
    private readonly Dictionary<string, string> environment;
    public JsonObject WorkspaceIdentity { get; }
    public JsonObject HostIdentity { get; }
    public string Context { get; }
    public string[] Absent { get; private set; } = [];
    public Discovery(string root, string sdk, string workspace, string directory, string toolchain, IReadOnlyDictionary<string, JsonObject> runtimeSnapshots)
    {
        this.root = root; this.sdk = sdk; this.workspace = workspace; this.directory = directory;
        if (OperatingSystem.IsLinux()) LinuxPlatform.Require(sdk);
        else if (!OperatingSystem.IsMacOS() || System.Runtime.InteropServices.RuntimeInformation.OSArchitecture != System.Runtime.InteropServices.Architecture.Arm64 || sdk != "/nix/store/f3kvj2nc26gn7rh5mnfnaa2dgy2p10v3-dotnet-sdk-10.0.400/share/dotnet") throw new InvalidDataException("Unqualified discovery host/toolchain");
        output = Path.Combine(directory, "output"); Directory.CreateDirectory(output);
        foreach (var name in new[] { "home", "tmp", "http" }) Directory.CreateDirectory(Path.Combine(output, name));
        runtimes = OperatingSystem.IsLinux() ? new[] { sdk }.Concat(LinuxPlatform.Libraries).ToArray() : Host.Run("/nix/var/nix/profiles/default/bin/nix-store", ["-qR", Path.GetDirectoryName(Path.GetDirectoryName(sdk))!], root).Split('\n', StringSplitOptions.RemoveEmptyEntries).Order(StringComparer.Ordinal).ToArray();
        roots["workspace"] = workspace;
        for (var i = 0; i < runtimes.Length; i++) roots["runtime-" + i] = runtimes[i];
        foreach (var name in new[] { "GraphExport", "EvaluationProbe" })
        {
            var target = Path.Combine(directory, "tools", name); FileTree.Copy(Path.Combine(root, "tools", name), target); roots[name] = target;
        }
        foreach (var (name, path) in roots) identities[name] = runtimeSnapshots.TryGetValue(path, out var known) ? (JsonObject)known.DeepClone() : FileTree.Snapshot(path, name.StartsWith("runtime-", StringComparison.Ordinal));
        WorkspaceIdentity = FileTree.Portable(workspace);
        HostIdentity = new JsonObject { ["osBuild"] = OperatingSystem.IsLinux() ? File.ReadAllText("/etc/os-release") : Host.Run("/usr/bin/sw_vers", ["-buildVersion"], root).Trim(), ["machine"] = "arm64", ["cpuCount"] = Environment.ProcessorCount };
        environment = new() { ["DOTNET_ROOT"] = sdk, ["DOTNET_HOST_PATH"] = Path.Combine(sdk, "dotnet"), ["HOME"] = Path.Combine(output, "home"), ["DOTNET_CLI_HOME"] = Path.Combine(output, "home"), ["TMPDIR"] = Path.Combine(output, "tmp"), ["NUGET_HTTP_CACHE_PATH"] = Path.Combine(output, "http"), ["PATH"] = sdk, ["TZ"] = "UTC", ["LANG"] = "en_US.UTF-8", ["LC_ALL"] = "en_US.UTF-8", ["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1", ["DOTNET_SKIP_FIRST_TIME_EXPERIENCE"] = "1", ["DOTNET_MULTILEVEL_LOOKUP"] = "0", ["DOTNET_EnableDiagnostics"] = "0", ["MSBUILDDISABLENODEREUSE"] = "1", ["MSBuildEnableWorkloadResolver"] = "false" };
        var runtimeIdentity = new JsonObject(); foreach (var name in roots.Keys.Where(k => k != "workspace")) runtimeIdentity[name] = Json.Digest(identities[name]);
        Context = Json.Digest(new JsonObject { ["policy"] = Policy, ["toolchain"] = toolchain, ["runtime"] = runtimeIdentity, ["host"] = HostIdentity.DeepClone(), ["workspaceDepth"] = workspace.Split('/').Length });
        File.WriteAllText(Path.Combine(output, "sandbox.sb"), Profile(roots.Values.Append(output), output));
    }
    internal static string Profile(IEnumerable<string> readRoots, string output)
    {
        var paths = readRoots.ToArray();
        var ancestors = paths.Concat(new[] { "/System/Library", "/usr/lib", "/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld", "/System/Cryptexes/OS/System/Library/dyld" }).SelectMany(p => Parents(p)).Distinct().Order(StringComparer.Ordinal);
        return "(version 1)\n(deny default)\n(allow process-exec process-fork signal sysctl-read mach-lookup)\n(allow file-read* file-test-existence (literal \"/\"))\n(allow file-read* file-test-existence file-map-executable (subpath \"/System/Library\") (subpath \"/usr/lib\") (subpath \"/usr/share/icu\") (subpath \"/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld\") (subpath \"/System/Cryptexes/OS/System/Library/dyld\") (literal \"/dev/null\") (literal \"/dev/urandom\") (literal \"/dev/random\"))\n(allow file-write* (literal \"/dev/null\") (subpath " + Json.Canonical(JsonValue.Create(output)) + "))\n" + string.Join('\n', paths.Select(p => "(allow file-read* file-test-existence file-map-executable (subpath " + Json.Canonical(JsonValue.Create(p)) + "))")) + "\n" + string.Join('\n', ancestors.Select(p => "(allow file-read-metadata file-test-existence (literal " + Json.Canonical(JsonValue.Create(p)) + "))"));
    }
    private static IEnumerable<string> Parents(string path)
    {
        while (Path.GetDirectoryName(path) is { } parent) { yield return parent; path = parent; }
    }
    private void Run(string name, JsonNode request)
    {
        var path = Path.Combine(output, name + "-request.json"); Json.Write(path, request);
        var start = OperatingSystem.IsLinux() ? LinuxPlatform.Discovery(roots.Values, output, workspace) : new ProcessStartInfo("/usr/bin/sandbox-exec") { WorkingDirectory = workspace, RedirectStandardOutput = true, RedirectStandardError = true };
        if (!OperatingSystem.IsLinux()) foreach (var arg in new[] { "-f", Path.Combine(output, "sandbox.sb") }) start.ArgumentList.Add(arg);
        foreach (var arg in new[] { Path.Combine(sdk, "dotnet"), Path.Combine(roots[name], "bin/Release/net10.0", name + ".dll"), "--request", path }) start.ArgumentList.Add(arg);
        start.Environment.Clear(); foreach (var (key, value) in environment) start.Environment[key] = value;
        using var process = Process.Start(start)!; var stdout = process.StandardOutput.ReadToEndAsync(); var stderr = process.StandardError.ReadToEndAsync();
        if (!process.WaitForExit(180000)) { process.Kill(true); throw new IOException("Discovery timed out"); }
        Task.WaitAll(stdout, stderr); File.WriteAllText(Path.Combine(output, name + ".log"), stdout.Result + stderr.Result);
        if (process.ExitCode != 0) throw new InvalidDataException("Sandboxed discovery failed: " + stdout.Result + stderr.Result);
    }
    public JsonNode Capture(string entry)
    {
        var properties = new JsonObject { ["Configuration"] = "Release", ["TargetFramework"] = "net10.0" };
        var entries = new JsonArray(new JsonObject { ["project"] = entry, ["globalProperties"] = properties });
        var augmented = (JsonArray)entries.DeepClone(); var targets = Path.Combine(roots["GraphExport"], "Bazel.GraphExport.targets");
        augmented[0]!["globalProperties"]!["BazelGraphExport"] = "true"; augmented[0]!["globalProperties"]!["CustomAfterMicrosoftCommonTargets"] = targets; augmented[0]!["globalProperties"]!["RestorePackagesPath"] = Path.Combine(workspace, ".nuget/packages");
        Run("EvaluationProbe", new JsonObject { ["workspace"] = workspace, ["dotnetRoot"] = sdk, ["sdkVersion"] = "10.0.400", ["entryPoints"] = augmented, ["properties"] = Json.Strings(["ProjectAssetsFile"]), ["items"] = new JsonArray(), ["mode"] = "recorded", ["output"] = Path.Combine(output, "evaluation.json") });
        var evidence = Json.Read(Path.Combine(output, "evaluation.json"))["rounds"]![0]!;
        var absent = new HashSet<string>(StringComparer.Ordinal); var trusted = new HashSet<string>(StringComparer.Ordinal);
        var testPackages = Json.Read(Path.Combine(root, "tools/discovery-test-packages.json"));
        var qualified = testPackages.Array("packages").Select(n => n!.GetValue<string>()).Concat(["polysharp/1.15.0", "microsoft.net.illink.tasks/10.0.11"]).ToHashSet(StringComparer.Ordinal);
        var imports = new HashSet<string>(["build/PolySharp.targets", "buildTransitive/PolySharp.targets", "build/Microsoft.NET.ILLink.Tasks.props", "build/Microsoft.NET.ILLink.Analyzers.props", "build/Microsoft.NET.ILLink.targets"], StringComparer.Ordinal);
        var packageChecker = new Packages(workspace, Path.Combine(output, "verified"), root); var index = 0;
        foreach (var node in evidence.Array("nodes"))
        {
            var project = Path.GetRelativePath(workspace, node!.String("project")); var assets = Path.GetRelativePath(workspace, node!["values"]!.String("ProjectAssetsFile"));
            if (packageChecker.Plan(Host.Safe(project), Host.Safe(assets), "net10.0").Any(p => !qualified.Contains(p.Key.ToLowerInvariant()))) throw new InvalidDataException("Discovery package behavior is not qualified");
            var staged = packageChecker.Stage(project, assets, "net10.0", (index++).ToString(System.Globalization.CultureInfo.InvariantCulture));
            var manifest = Json.Read(Path.Combine(output, "verified", staged.Manifest));
            foreach (var package in manifest.Array("packages"))
            {
                var folder = Path.Combine(workspace, ".nuget/packages", package!.String("path"));
                var names = package.Array("files").Select(f => f!.String("path")).ToHashSet(StringComparer.Ordinal);
                foreach (var file in FileTree.Files(folder)) if (!names.Contains(Path.GetRelativePath(folder, file)) && Path.GetFileName(file) != ".nupkg.metadata") throw new InvalidDataException("Unexpected package payload");
                foreach (var name in names)
                {
                    var path = Path.Combine(folder, name);
                    if (imports.Contains(name)) trusted.Add(path);
                    if (testPackages["imports"]?[package.String("path") + "/" + name] is { } expected)
                    {
                        if (Json.Sha(File.ReadAllBytes(path)) != expected.GetValue<string>()) throw new InvalidDataException("Package import differs from reviewed bytes");
                        trusted.Add(path);
                    }
                }
            }
        }
        packageChecker.Verify();
        foreach (var observation in evidence.Array("observations"))
        {
            var path = observation!.String("path");
            if (Host.Within(path, output)) throw new InvalidDataException("Discovery consulted scratch state");
            if (roots.Values.Any(p => Host.Within(path, p))) continue;
            if (observation.String("operation") is not ("exists" or "file-exists" or "directory-exists") || observation.String("result") != "false" || Path.Exists(path)) throw new InvalidDataException("Undeclared discovery observation: " + path);
            absent.Add(path);
        }
        var sdkImports = Json.Read(Path.Combine(root, "tools/discovery-sdk-imports.json"))["imports"]!;
        foreach (var node in evidence.Array("nodes"))
            foreach (var import in node!.Array("imports"))
            {
                var path = import!.String("path");
                if (Host.Within(path, workspace)) { if (!trusted.Contains(path)) CompileBoundary.CheckXml(path); }
                else if (path != targets && !QualifiedImport(sdkImports, path, import.String("sha256"))) throw new InvalidDataException("Unqualified SDK import: " + path);
            }
        Absent = absent.Order(StringComparer.Ordinal).ToArray();
        Run("GraphExport", new JsonObject { ["schemaVersion"] = 1, ["workspace"] = workspace, ["dotnetRoot"] = sdk, ["sdkVersion"] = "10.0.400", ["packageRoot"] = Path.Combine(workspace, ".nuget/packages"), ["entryPoints"] = entries, ["output"] = Path.Combine(output, "graph.json") });
        Verify(); return Json.Read(Path.Combine(output, "graph.json"));
    }
    private bool QualifiedImport(JsonNode reviewed, string path, string hash)
    {
        if (reviewed[path]?.GetValue<string>() == hash) return true;
        if (!OperatingSystem.IsLinux() || !Host.Within(path, sdk)) return false;
        // The Linux SDK may reuse only already-reviewed import bytes at the
        // corresponding SDK-relative path. New imports still fail closed.
        var suffix = "/share/dotnet/" + Path.GetRelativePath(sdk, path);
        return reviewed.AsObject().Any(p => p.Key.EndsWith(suffix, StringComparison.Ordinal) && p.Value?.GetValue<string>() == hash);
    }
    public JsonNode Export(string entry)
    {
        Run("GraphExport", new JsonObject { ["schemaVersion"] = 1, ["workspace"] = workspace, ["dotnetRoot"] = sdk, ["sdkVersion"] = "10.0.400", ["packageRoot"] = Path.Combine(workspace, ".nuget/packages"), ["entryPoints"] = new JsonArray(new JsonObject { ["project"] = entry, ["globalProperties"] = new JsonObject { ["Configuration"] = "Release", ["TargetFramework"] = "net10.0" } }), ["output"] = Path.Combine(output, "revalidated.json") });
        return Json.Read(Path.Combine(output, "revalidated.json"));
    }
    public bool Rebase(JsonNode receipt)
    {
        if (receipt["policy"]?.GetValue<string>() != Policy || receipt["context"]?.GetValue<string>() != Context) return false;
        var old = receipt.String("workspace"); var oldParents = Parents(old).ToArray(); var newParents = Parents(workspace).ToArray();
        if (oldParents.Length != newParents.Length) return false;
        Absent = receipt.Array("absent").Select(n =>
        {
            var path = n!.GetValue<string>(); var parent = Path.GetDirectoryName(path); var i = Array.IndexOf(oldParents, parent);
            return i >= 0 ? Path.Combine(newParents[i], Path.GetFileName(path)) : path;
        }).ToArray();
        return Absent.All(p => !Path.Exists(p));
    }
    public JsonObject Receipt(string entry, string plan) => new() { ["policy"] = Policy, ["context"] = Context, ["entry"] = entry, ["workspace"] = workspace, ["inputs"] = WorkspaceIdentity.DeepClone(), ["absent"] = Json.Strings(Absent), ["payload"] = Json.Digest(FileTree.Snapshot(plan)) };
    public void Verify(FileTree.Verification? verification = null)
    {
        verification ??= new FileTree.Verification();
        foreach (var (name, path) in roots) verification.Verify(path, identities[name], name.StartsWith("runtime-", StringComparison.Ordinal));
        if (Absent.Any(Path.Exists)) throw new InvalidDataException("External namespace changed during consumption");
    }
}
