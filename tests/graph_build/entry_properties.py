"""Explicit root properties retain mixed frameworks and invalidate selected nodes."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-entry-properties-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        (root / 'empty-input').mkdir()
        for name, framework in [('A', 'net10.0'), ('B', None), ('Common', None)]:
            folder = root / name
            folder.mkdir()
            selected = ('<TargetFramework>' + framework + '</TargetFramework>' if framework else
                        '<TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks>')
            reference = '<ItemGroup><ProjectReference Include="../Common/Common.csproj"/></ItemGroup>' if name != 'Common' else ''
            (folder / (name + '.csproj')).write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>' + selected +
                '</PropertyGroup>' + reference + '</Project>')
            (folder / 'Code.cs').write_text('public class ' + name + ' { public static int Value => Common.Value; }' if name != 'Common' else
                'public class Common { public const int Value = 11; }')
        entries = ['A/A.csproj', 'B/B.csproj']
        mapping = base / 'mapping.json'
        declarations = {'A/A.csproj': {}, 'B/B.csproj': {'TargetFramework': 'net10.0-windows'}}
        sync = ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll'
        cache, report = base / 'cache', base / 'report.json'
        def generate(success=True, scratch=False):
            defaults = {'inputDirectories': ['empty-input']}
            if scratch:
                defaults['temporaryDirectories'] = ['$(IntermediateOutputPath)temporary']
            mapping.write_text(json.dumps({'entryProperties': declarations, 'projectDefaults': defaults}))
            return run(DOTNET, sync, root, SDK / 'sdk/10.0.400', *entries, '--graph', '--framework', 'net10.0',
                       '--mappings', mapping, success=success)
        def build(success=True):
            for folder in ['A', 'B', 'Common']:
                for directory in ['bin', 'obj/Release']:
                    shutil.rmtree(root / folder / directory, ignore_errors=True)
            result = run(DOTNET, RUNNER, 'action', root, root / 'graph.generated.json', report, cache, success=success)
            return json.loads(report.read_text()) if success else result.stderr
        generate()
        contract = json.loads((root / 'graph.generated.json').read_text())
        assert contract['Version'] == 6 and contract['EntryProperties'] == declarations
        assert contract['InputDirectories'] == ['empty-input']
        variants = [value for project in contract['Projects'].values() for value in project['Configurations']]
        assert sum(bool(value['OutputDirectories']) for value in variants) == 4, variants
        assert build()['misses'] == 4
        baseline = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in
                    ['A/bin/Release/net10.0/A.dll', 'B/bin/Release/net10.0-windows/B.dll',
                     'Common/bin/Release/net10.0/Common.dll', 'Common/bin/Release/net10.0-windows/Common.dll']}
        driver = base / 'raw-driver'
        driver.mkdir()
        shutil.copyfile(ROOT / 'tests/graph_build/upstream/RuntimeRawGraph.cs.txt', driver / 'Program.cs')
        shutil.copyfile(ROOT / 'tests/graph_build/upstream/RuntimeRawGraph.csproj.txt', driver / 'Raw.csproj')
        run(DOTNET, 'build', driver / 'Raw.csproj', '-c', 'Release', '-p:UseSharedCompilation=false')
        for folder in ['A', 'B', 'Common']:
            for directory in ['bin', 'obj/Release']:
                shutil.rmtree(root / folder / directory, ignore_errors=True)
        run(DOTNET, driver / 'bin/Release/net10.0/Raw.dll', root, root / 'graph.generated.json', 'build')
        assert all(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest for name, digest in baseline.items()), 'Raw mixed-root byte parity failed'
        assert build()['hits'] == 4
        assert all(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest for name, digest in baseline.items())
        declarations['B/B.csproj']['TargetFramework'] = 'net10.0'
        generate()
        observed = build()
        assert (observed['hits'], observed['misses']) == (3, 1), observed
        assert hashlib.sha256((root / 'A/bin/Release/net10.0/A.dll').read_bytes()).hexdigest() == baseline['A/bin/Release/net10.0/A.dll']
        assert hashlib.sha256((root / 'B/bin/Release/net10.0/B.dll').read_bytes()).hexdigest() != baseline['B/bin/Release/net10.0-windows/B.dll']
        generate(scratch=True)
        combined = json.loads((root / 'graph.generated.json').read_text())
        assert combined['Version'] == 6 and combined['InputDirectories'] == ['empty-input']
        assert len(combined['TemporaryDirectories']) == 4
        assert build()['misses'] == 4, 'Changing the global cleanup contract must invalidate snapshots'
        assert build()['hits'] == 4
        for key in ['PathMap', 'RestoreSources', 'MSBuildSDKsPath', 'UseSharedCompilation', 'NetCoreSdkRoot']:
            declarations['A/A.csproj'][key] = 'forbidden'
            assert 'graph entry property' in generate(False).stderr
            del declarations['A/A.csproj'][key]
        declarations['Unselected.csproj'] = {'TargetFramework': 'net10.0'}
        assert 'selected graph root' in generate(False).stderr
        del declarations['Unselected.csproj']
        declarations['B/B.csproj']['targetframework'] = 'ambiguous'
        assert 'graph entry property' in generate(False).stderr
        del declarations['B/B.csproj']['targetframework']
        generate()
        contract = json.loads((root / 'graph.generated.json').read_text())
        contract['Version'] = 4
        (root / 'graph.generated.json').write_text(json.dumps(contract))
        assert 'require graph contract version 6' in build(False)
        declarations['A/A.csproj']['QualificationChoice'] = 'FLAVOR_A'
        declarations['B/B.csproj']['QualificationChoice'] = 'FLAVOR_B'
        before = (root / 'graph.generated.bzl').read_bytes()
        assert 'ambiguous across configured nodes' in generate(False).stderr
        assert (root / 'graph.generated.bzl').read_bytes() == before
        print('PASS: mixed entry frameworks, configured dependency identity, full replay, selective property invalidation and fail-closed overrides')


if __name__ == '__main__':
    main()
