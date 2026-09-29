"""Qualify target-result replay and dependency copies on a three-project graph."""

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, RUNNER, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='generic-replay-') as temporary:
        work = Path(temporary).resolve()
        root = work / 'workspace'
        root.mkdir()
        contract = fixture(root)
        contract['Properties']['DisableTransitiveProjectReferences'] = 'true'
        project = root / 'P0/P0.csproj'
        project.write_text(project.read_text().replace('</Project>', '<ItemGroup><EmbeddedResource Include="Resource.txt" /></ItemGroup></Project>'))
        (root / 'P0/Resource.txt').write_text('first resource')
        contract['Projects']['P0/P0.csproj']['Inputs'].append('P0/Resource.txt')
        for i in range(3):
            declaration = contract['Projects'][f'P{i}/P{i}.csproj']
            declaration['ReferenceBoundary'] = True
            declaration['DependencyCopies'] = {
                f'P{i}/bin/Release/net10.0/{prefix}P{dependency}.{extension}':
                f'P{dependency}/bin/Release/net10.0/P{dependency}.{extension}'
                for dependency in range(i) for extension in ('dll', 'pdb') for prefix in ('', 'publish/')
            }
        manifest = work / 'contract.json'
        report = work / 'report.json'
        manifest.write_text(json.dumps(contract))

        def clean():
            for project in contract['Projects'].values():
                for relative in project['OutputDirectories']:
                    shutil.rmtree(root / relative, ignore_errors=True)

        def build(target='Build', cache='cache', expected=None):
            clean()
            run(DOTNET, RUNNER, 'build', root, manifest, report, work / cache, target)
            result = json.loads(report.read_text())
            if expected is not None:
                assert result['hits'] == expected, result
            return result

        def outputs():
            return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for project in contract['Projects'].values()
                    for relative in project['OutputDirectories']
                    for path in (root / relative).rglob('*') if path.is_file() and not path.name.endswith('.AssemblyReference.cache')}

        def execute(expected, publish=False):
            app = root / ('P2/bin/Release/net10.0/publish/P2.dll' if publish else 'P2/bin/Release/net10.0/P2.dll')
            assert run(DOTNET, app).stdout.strip() == expected

        results = {'base': build(expected=0), 'replay': build(expected=3)}
        execute('1')
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; }')
        results['body'] = build(expected=2)
        execute('2')
        edited = outputs()
        results['body_control'] = build(cache='control', expected=0)
        assert edited == outputs(), sorted(k for k in edited if edited[k] != outputs().get(k))
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; public static int Extra() => 3; }')
        results['api'] = build(expected=1)
        execute('2')
        (root / 'P0/Resource.txt').write_text('edited resource')
        results['resource'] = build(expected=2)
        resource_outputs = outputs()
        results['resource_control'] = build(cache='resource-control', expected=0)
        assert resource_outputs == outputs()
        results['publish'] = build(target='Publish', expected=0)
        execute('2', publish=True)
        results['publish_replay'] = build(target='Publish', expected=3)
        execute('2', publish=True)
        clean()
        for path in (work / 'cache').rglob('*.dll'):
            path.write_bytes(b'corrupt')
        failure = run(DOTNET, RUNNER, 'build', root, manifest, report, work / 'cache', 'Publish', success=False)
        assert 'Corrupt graph snapshot' in failure.stderr, failure.stderr
        print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
