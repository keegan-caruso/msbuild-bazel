"""Native controls for shared digest observations and output ownership facts."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class InputObservationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="sync-observations-")
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        sources = ["tools/ProjectCache/FileObservation.cs", "tools/OutputOwnershipIndex.cs", "tools/GraphBuild/OutputOwnership.cs", "tools/NoLinkTree.cs", "tools/ConfiguredProjectKey.cs", "tools/ProjectCache/BuildSeed.cs"]
        (cls.directory / "Controls.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
            '<TargetFramework>net11.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
            '</PropertyGroup><ItemGroup>' + ''.join(f'<Compile Include="{ROOT / source}" />' for source in sources) +
            '<Reference Include="Microsoft.Build" HintPath="$(MSBuildBinPath)/Microsoft.Build.dll" />'
            '<Reference Include="Microsoft.Build.Framework" HintPath="$(MSBuildBinPath)/Microsoft.Build.Framework.dll" />'
            '<AssemblyMetadata Include="SelectedMSBuildBinPath" Value="$(MSBuildBinPath)" /></ItemGroup></Project>')
        (cls.directory / "Program.cs").write_text(CONTROLS)
        result = subprocess.run(["bash", str(ROOT / "scripts/dotnet.sh"), "build", str(cls.directory / "Controls.csproj"),
            "-c", "Release", "-warnaserror"], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def control(self, name):
        result = subprocess.run([str(Path(os.environ["RULES_MSBUILD_DOTNET_ROOT"]) / "dotnet"),
            str(self.directory / "bin/Release/net11.0/Controls.dll"), name], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_digest_encodings_modes_and_mutation(self):
        self.control("digests")

    def test_ownership_matches_pairwise_policy_and_runner_rejections(self):
        self.control("ownership")

    def test_configured_project_node_and_request_keys(self):
        self.control("keys")

    def test_tree_inventories_ordering_and_link_rejection(self):
        self.control("trees")

    def test_independent_ownership_scaling(self):
        print(self.control("scaling"), end="")


CONTROLS = r'''
using System.Diagnostics;
using System.Globalization;
using System.Security.Cryptography;
using System.Reflection;
using System.Text;
using RulesMSBuild;
using RulesMSBuild.GraphBuild;
using RulesMSBuild.ProjectCache;

static void Check(bool value, string message)
{
    if (!value) throw new Exception(message);
}
static bool Overlap(string left, string right) => left == right || left.StartsWith(right + "/", StringComparison.Ordinal) || right.StartsWith(left + "/", StringComparison.Ordinal);
if (args[0] == "digests")
{
    var path = Path.GetTempFileName();
    try
    {
        foreach (var size in new[] { 0, 1, 131073 })
        {
            File.WriteAllBytes(path, Enumerable.Range(0, size).Select(i => (byte)i).ToArray());
            foreach (var mode in new[] { 384, 493, 1023 })
            {
                if (!OperatingSystem.IsWindows()) File.SetUnixFileMode(path, (UnixFileMode)mode);
                var observed = FileObservation.Read(path);
                var content = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path)));
                var actualMode = OperatingSystem.IsWindows() ? 0 : (int)File.GetUnixFileMode(path);
                Check(observed.QualificationDigest == content.ToLowerInvariant() + ":" + (actualMode & 511).ToString(CultureInfo.InvariantCulture), "qualification encoding");
                var expected = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(content + ":" + actualMode.ToString(CultureInfo.InvariantCulture)))).ToLowerInvariant();
                Check(observed.SeedDigest == expected, "seed encoding including special mode bits");
            }
        }
        var before = FileObservation.Read(path);
        var timestamp = File.GetLastWriteTimeUtc(path);
        var bytes = File.ReadAllBytes(path); bytes[0] ^= 1; File.WriteAllBytes(path, bytes); File.SetLastWriteTimeUtc(path, timestamp);
        var after = FileObservation.Read(path);
        Check(before.QualificationDigest != after.QualificationDigest && before.SeedDigest != after.SeedDigest, "same-size/time mutation");
    }
    finally { File.Delete(path); }
}
else if (args[0] == "ownership")
{
    var random = new Random(602);
    for (var iteration = 0; iteration < 150; iteration++)
    {
        var owners = Enumerable.Range(0, 16).Select(_ => new object()).ToArray();
        var directories = owners.SelectMany(owner => Enumerable.Range(0, random.Next(3)).Select(_ => (owner, path: "tree/" + random.Next(8) + (random.Next(2) == 0 ? "/nested" : "")))).ToArray();
        var files = owners.SelectMany(owner => Enumerable.Range(0, random.Next(4)).Select(_ => (owner, path: "tree/" + random.Next(8) + (random.Next(2) == 0 ? "/nested" : "") + "/file" + random.Next(3)))).ToArray();
        var index = new OutputOwnershipIndex<object>(directories, files);
        var expected = owners.Where(owner => owners.Any(other => !ReferenceEquals(owner, other) &&
            (files.Where(p => p.owner == owner).Any(left => files.Any(right => right.owner == other && left.path == right.path)) ||
             directories.Where(p => p.owner == owner).Any(left => files.Any(right => right.owner == other && right.path.StartsWith(left.path + "/", StringComparison.Ordinal)) || directories.Any(right => right.owner == other && Overlap(left.path, right.path))) ||
             directories.Where(p => p.owner == other).Any(right => files.Any(left => left.owner == owner && left.path.StartsWith(right.path + "/", StringComparison.Ordinal)))))).ToHashSet();
        Check(index.ConflictingOwners().SetEquals(expected), "pairwise conflict policy");
        foreach (var path in files.Select(p => p.path).Append("tree/80/file0"))
        {
            var expectedOwners = owners.Where(owner => files.Any(p => p.owner == owner && p.path == path) || directories.Any(p => p.owner == owner && path.StartsWith(p.path + "/", StringComparison.Ordinal))).ToHashSet();
            Check(index.Owners(path).ToHashSet().SetEquals(expectedOwners), "file ownership and component boundaries");
        }
    }
    var a = new object(); var b = new object();
    var valid = new OutputOwnership<object>("/root", [(a, "/root/a"), (a, "/root/a/nested"), (b, "/root/ab")], [(a, "/root/a/file")], []);
    valid.Validate(); Check(valid.Owner("/root/a/nested/file") == a && valid.Owner("/root/ab/file") == b, "runner owner");
    void Reject((object, string)[] dirs, (object, string)[] files)
    {
        try { new OutputOwnership<object>("/root", dirs, files, []).Validate(); }
        catch (InvalidDataException) { return; }
        throw new Exception("runner accepted overlap");
    }
    Reject([(a, "/root/a"), (b, "/root/a/nested")], []);
    Reject([(a, "/root/a")], [(a, "/root/a")]);
    Reject([], [(a, "/root/a"), (b, "/root/a")]);
    Reject([(b, "/root/a/nested")], [(a, "/root/a")]);
}
else if (args[0] == "scaling")
{
    foreach (var count in new[] { 1000, 4000, 16000 })
    {
        var owners = Enumerable.Range(0, count).Select(_ => new object()).ToArray();
        var watch = Stopwatch.StartNew();
        var index = new OutputOwnershipIndex<object>(owners.Select((owner, i) => (owner, "projects/" + i + "/bin")), owners.Select((owner, i) => (owner, "projects/" + i + "/obj/ref.dll")));
        Check(index.ConflictingOwners().Count == 0, "independent conflicts");
        foreach (var (owner, i) in owners.Select((owner, i) => (owner, i))) Check(index.Owners("projects/" + i + "/bin/a.dll").Single() == owner, "independent owner");
        Console.WriteLine($"OWNERSHIP_SCALING nodes={count} elapsed_ms={watch.Elapsed.TotalMilliseconds:F2} prior_ordered_pairs={(long)count * (count - 1)}");
    }
}
if (args[0] == "trees")
{
    var root = Directory.CreateTempSubdirectory("no-link-tree-").FullName;
    try
    {
        Directory.CreateDirectory(Path.Combine(root, "z-dir", "empty"));
        Directory.CreateDirectory(Path.Combine(root, "a-empty"));
        File.WriteAllText(Path.Combine(root, "z-dir", "inside.txt"), "inside");
        File.WriteAllText(Path.Combine(root, "b.txt"), "root");
        string Relative(string path) => Path.GetRelativePath(root, path).Replace('\\', '/');
        Check(NoLinkTree.Entries(root, "entry: ", ordered: true).Select(Relative).SequenceEqual(
            new[] { "a-empty", "b.txt", "z-dir", "z-dir/empty", "z-dir/inside.txt" }), "ordered directory inventory");
        Check(NoLinkTree.Files(root, "file: ").Select(Relative).ToHashSet().SetEquals(
            new[] { "b.txt", "z-dir/inside.txt" }), "file-only inventory");
        void Rejected(Func<IEnumerable<string>> walk, string expected)
        {
            try { _ = walk().ToArray(); throw new Exception("Linked tree accepted"); }
            catch (InvalidDataException error) { Check(error.Message == expected, "link diagnostic changed"); }
        }
        var alias = root + "-alias";
        try
        {
            Directory.CreateSymbolicLink(alias, root);
            Rejected(() => NoLinkTree.Entries(alias, "entry: "), "entry: " + alias);
            Check(NoLinkTree.Files(alias, "file: ").Count() == 2, "file walker changed root-validation policy");
        }
        finally { Directory.Delete(alias); }
        foreach (var kind in new[] { "file", "directory", "dangling" })
        {
            var link = Path.Combine(root, "link");
            if (kind == "directory") Directory.CreateSymbolicLink(link, Path.Combine(root, "z-dir"));
            else File.CreateSymbolicLink(link, Path.Combine(root, kind == "file" ? "b.txt" : "missing"));
            try
            {
                Rejected(() => NoLinkTree.Entries(root, "entry: "), "entry: " + link);
                Rejected(() => NoLinkTree.Files(root, "file: "), "file: " + link);
            }
            finally { if (kind == "directory") Directory.Delete(link); else File.Delete(link); }
        }
    }
    finally { Directory.Delete(root, recursive: true); }
    Console.WriteLine("PASS: tree membership, empty directories, ordinal depth-first order, roots and file/directory/dangling links");
}
if (args[0] == "keys")
{
    var engine = Assembly.GetExecutingAssembly().GetCustomAttributes<AssemblyMetadataAttribute>()
        .Single(attribute => attribute.Key == "SelectedMSBuildBinPath").Value!;
    System.Runtime.Loader.AssemblyLoadContext.Default.Resolving += (context, name) =>
        File.Exists(Path.Combine(engine, name.Name + ".dll")) ? context.LoadFromAssemblyPath(Path.Combine(engine, name.Name + ".dll")) : null;
    Environment.SetEnvironmentVariable("MSBUILD_EXE_PATH", Path.Combine(engine, "MSBuild.dll"));
    var root = Directory.CreateTempSubdirectory("configured-project-").FullName;
    try
    {
        var project = Path.Combine(root, OperatingSystem.IsWindows() ? "a-b.proj" : "a|b.proj");
        File.WriteAllText(project, "<Project><Target Name=\"Build\" /></Project>");
        var graph = new Microsoft.Build.Graph.ProjectGraph(new[] {
            new Microsoft.Build.Graph.ProjectGraphEntryPoint(project, new Dictionary<string, string> { ["A"] = "x;B=y" }),
            new Microsoft.Build.Graph.ProjectGraphEntryPoint(project, new Dictionary<string, string> { ["A"] = "x", ["B"] = "y" }) });
        string Legacy(Microsoft.Build.Execution.ProjectInstance state) => state.FullPath + "|" + string.Join(";",
            state.GlobalProperties.OrderBy(pair => pair.Key, StringComparer.Ordinal).Select(pair => pair.Key + "=" + pair.Value));
        Check(graph.ProjectNodes.Count == 2, "MSBuild collapsed distinct configurations");
        Check(graph.ProjectNodes.Select(node => Legacy(node.ProjectInstance)).Distinct().Count() == 1, "Legacy collision fixture stopped colliding");
        Check(graph.ProjectNodes.ToDictionary(node => ConfiguredProjectKey.Create(node.ProjectInstance)).Count == 2, "Configured nodes collided");
        foreach (var node in graph.ProjectNodes)
        {
            var state = node.ProjectInstance;
            var request = new Microsoft.Build.Execution.BuildRequestData(state, new[] { "Build" });
            Check(ConfiguredProjectKey.Create(state) == ConfiguredProjectKey.Create(request), "Actual node/request forms differ");
            var pathRequest = new Microsoft.Build.Execution.BuildRequestData(project, state.GlobalProperties, null, new[] { "Build" }, null);
            Check(ConfiguredProjectKey.Create(state) == ConfiguredProjectKey.Create(pathRequest), "Actual path request form differs");
            var properties = state.GlobalProperties.Reverse().ToDictionary(pair => pair.Key, pair => pair.Value);
            var reordered = new Microsoft.Build.Execution.ProjectInstance(project, properties, null);
            Check(ConfiguredProjectKey.Create(reordered) == ConfiguredProjectKey.Create(state), "Property insertion order changed identity");
        }
        var specialKeys = new HashSet<string> { ConfiguredProjectKey.Create(new Microsoft.Build.Execution.ProjectInstance(project)) };
        foreach (var value in new[] { "", "a=b;c|d", "quote\"\\newline\n", "caf\u00e9/\U0001f642" })
        {
            var state = new Microsoft.Build.Execution.ProjectInstance(project, new Dictionary<string, string> { ["A"] = value }, null);
            Check(ConfiguredProjectKey.Create(state) == ConfiguredProjectKey.Create(new Microsoft.Build.Execution.BuildRequestData(state, new[] { "Build" })), "Special value node/request mismatch");
            Check(specialKeys.Add(ConfiguredProjectKey.Create(state)), "Empty/absent or special values collided");
        }
        BuildSeedProof.RequireVersion(BuildSeedProof.Version);
        try { BuildSeedProof.RequireVersion(1); throw new Exception("Legacy seed accepted"); }
        catch (InvalidDataException error) { Check(error.Message.Contains("rerun your sync target"), "Legacy seed regeneration guidance missing"); }
    }
    finally { Directory.Delete(root, recursive: true); }
    Console.WriteLine("PASS: actual configured-node collision, request parity, order, special values and legacy-seed regeneration");
}
'''
