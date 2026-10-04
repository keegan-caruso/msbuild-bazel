"""Per-pass path reuse retains content, mode, symlink and post-build checks."""

import json
from pathlib import Path
import tempfile

from qualify import DOTNET, ROOT, RUNNER, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-input-integrity-') as temporary:
        work = Path(temporary).resolve()
        root = work / 'workspace'
        root.mkdir()
        contract = fixture(root)
        data = root / 'P0/data.txt'
        data.write_text('original')
        contract['Projects']['P0/P0.csproj']['Inputs'].append('P0/data.txt')
        project = root / 'P0/P0.csproj'
        project.write_text(project.read_text().replace('</Project>',
            '<Target Name="MutateDeclaredInput" BeforeTargets="CoreCompile">'
            '<WriteLinesToFile File="data.txt" Lines="modified" Overwrite="true" />'
            '</Target></Project>'))
        manifest = work / 'contract.json'
        manifest.write_text(json.dumps(contract))
        failure = run(DOTNET, RUNNER, 'build', root, manifest, work / 'report.json', work / 'cache', success=False)
        assert 'Build modified a declared input: P0/data.txt' in failure.stderr, failure.stderr
        assert not list((work / 'cache').glob('*/manifest.json'))

        # The ownership plan exists before targets run. A later output symlink
        # must still fail the real artifact path check before external bytes publish.
        linked_root = work / 'linked-workspace'
        linked_root.mkdir()
        linked_contract = fixture(linked_root)
        outside = work / 'linked-outside'
        outside.mkdir()
        marker = outside / 'marker.txt'
        marker.write_text('outside')
        project = linked_root / 'P0/P0.csproj'
        project.write_text(project.read_text().replace('</Project>',
            '<Target Name="LinkOutput" AfterTargets="Build"><Exec Command="ln -s &quot;' + str(outside) +
            '&quot; &quot;$(TargetDir)foreign&quot;" /></Target></Project>'))
        linked_manifest = work / 'linked-contract.json'
        linked_manifest.write_text(json.dumps(linked_contract))
        failure = run(DOTNET, RUNNER, 'build', linked_root, linked_manifest, work / 'linked-report.json', work / 'linked-cache', success=False)
        assert 'Symlinks are not supported' in failure.stderr, failure.stderr
        assert marker.read_text() == 'outside'

        # Exercise the production path/digest helpers directly, without copying
        # or mutating the real SDK just to change one executable bit.
        harness = work / 'harness'
        harness.mkdir()
        (harness / 'Harness.csproj').write_text(
            '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>'
            '<OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable>'
            '</PropertyGroup><ItemGroup>' + ''.join(f'<Compile Include="{ROOT}/tools/GraphBuild/{name}.cs" />'
            for name in ['Contract', 'GraphProfile']) + '</ItemGroup></Project>')
        (harness / 'Program.cs').write_text('''
using RulesMSBuild.GraphBuild;
var root = Path.Combine(args[0], "paths");
Directory.CreateDirectory(Path.Combine(root, "directory"));
var a = Path.Combine(root, "directory/a");
var b = Path.Combine(root, "directory/b");
File.WriteAllText(a, "first");
File.WriteAllText(b, "second");
var files = new ContractFiles(root, root);
var paths = new[] { "directory/a", "directory/b" };
var batch = files.ResolveInputs(paths);
if (paths.Any(p => batch[p] != files.Resolve(p))) throw new Exception("Path mismatch");
var stamp = File.GetLastWriteTimeUtc(a);
string CheckedDigest()
{
    var serial = ContractFiles.TreeDigest(root);
    foreach (var parallelism in new[] { 2, 4 })
        if (ContractFiles.TreeDigest(root, parallelism) != serial) throw new Exception("Parallel tree order or digest changed");
    return serial;
}
var original = CheckedDigest();
File.WriteAllText(a, "other");
File.SetLastWriteTimeUtc(a, stamp);
if (original == CheckedDigest()) throw new Exception("Content change ignored");
if (!OperatingSystem.IsWindows())
{
    original = CheckedDigest();
    File.SetUnixFileMode(a, File.GetUnixFileMode(a) ^ UnixFileMode.UserExecute);
    if (original == CheckedDigest()) throw new Exception("SDK mode change ignored");
    Directory.Move(Path.Combine(root, "directory"), Path.Combine(args[0], "outside"));
    Directory.CreateSymbolicLink(Path.Combine(root, "directory"), Path.Combine(args[0], "outside"));
    try { files.ResolveInputs(paths); throw new Exception("New ancestor link accepted"); }
    catch (InvalidDataException) { }
}
foreach (var invalid in new[] { "../outside/a", "/absolute", "directory//a", "directory/./a" })
{
    try { files.ResolveInputs([invalid]); throw new Exception("Invalid path accepted"); }
    catch (InvalidDataException) { }
}
Console.WriteLine("PASS: batch path resolution, fresh symlink checks, timestamp-independent bytes and SDK modes");
''')
        run(DOTNET, 'build', harness / 'Harness.csproj', '-c', 'Release', '--nologo', '-p:UseSharedCompilation=false')
        result = run(DOTNET, harness / 'bin/Release/net10.0/Harness.dll', work)
        print(result.stdout.strip())
        print('PASS: target input mutation and post-plan output symlink rejected before publishing those bytes')


if __name__ == '__main__':
    main()
