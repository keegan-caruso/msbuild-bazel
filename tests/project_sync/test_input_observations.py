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
        sources = ["tools/ProjectCache/FileObservation.cs", "tools/OutputOwnershipIndex.cs", "tools/GraphBuild/OutputOwnership.cs"]
        (cls.directory / "Controls.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
            '<TargetFramework>net11.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
            '</PropertyGroup><ItemGroup>' + ''.join(f'<Compile Include="{ROOT / source}" />' for source in sources) + '</ItemGroup></Project>')
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

    def test_independent_ownership_scaling(self):
        print(self.control("scaling"), end="")


CONTROLS = r'''
using System.Diagnostics;
using System.Globalization;
using System.Security.Cryptography;
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
'''
