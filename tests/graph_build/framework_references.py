"""Offline .NET Framework reference assemblies come from the declared package lock."""

import argparse
import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('packages', type=Path, help='NuGet cache containing Microsoft.NETFramework.ReferenceAssemblies and .net462, version 1.0.3')
    packages = parser.parse_args().packages.resolve()
    with tempfile.TemporaryDirectory(prefix='graph-framework-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        (root / 'Library').mkdir(parents=True)
        project = root / 'Library/Library.csproj'
        project.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net462</TargetFramework></PropertyGroup></Project>')
        (root / 'Library/Code.cs').write_text('public class Library { public static string Value => System.Environment.NewLine; }')
        names = ['microsoft.netframework.referenceassemblies', 'microsoft.netframework.referenceassemblies.net462']
        manifest = base / 'inputs.json'
        manifest.write_text(json.dumps({'Inputs': [], 'PackageLock': ':packages', 'Packages': [
            {'Id': name, 'Version': '1.0.3', 'Runfile': name + '/1.0.3'} for name in names]}))
        sync = [DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root, SDK / 'sdk/10.0.400',
                'Library/Library.csproj', '--package-build', '--inputs', manifest, '--runfiles', packages]
        run(*sync)
        feed = root / '.package-source'
        feed.mkdir()
        for name in names:
            archive = packages / name / '1.0.3' / (name + '.1.0.3.nupkg')
            shutil.copy2(archive, feed / archive.name)
        report = base / 'report.json'
        def build(hits):
            for folder in ['bin', 'obj']:
                shutil.rmtree(root / 'Library' / folder, ignore_errors=True)
            run(DOTNET, RUNNER, 'action', root, root / 'graph.generated.json', report, base / 'cache')
            assert json.loads(report.read_text())['hits'] == hits, report.read_text()
            return (root / 'Library/bin/Release/net462/Library.dll').read_bytes()
        assert build(0) == build(1)
        project.write_text(project.read_text().replace('</Project>', '<ItemGroup><Reference Include="UnownedAssembly" /></ItemGroup></Project>'))
        assert 'SDK/package-owned assembly references' in run(*sync, success=False).stderr
        print('PASS: package-owned Framework references, offline build/replay, undeclared assembly rejection')


if __name__ == '__main__':
    main()
