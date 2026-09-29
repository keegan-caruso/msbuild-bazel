"""Generated contracts preserve compiler visibility and refresh implementation copies."""

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, fixture, run

SYNC = ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll'


def qualify(transitive):
    with tempfile.TemporaryDirectory(prefix='graph-invalidation-') as temporary:
        work = Path(temporary).resolve()
        root = work / 'workspace'
        root.mkdir()
        fixture(root)
        (root / 'Directory.Build.props').write_text('<Project><PropertyGroup>'
            f'<DisableTransitiveProjectReferences>{str(not transitive).lower()}</DisableTransitiveProjectReferences>'
            '<GenerateDocumentationFile>true</GenerateDocumentationFile></PropertyGroup></Project>')
        manifest = root / 'graph.generated.json'
        report = work / 'report.json'

        def sync():
            run(DOTNET, SYNC, root, SDK / 'sdk/10.0.400', 'P2/P2.csproj', '--graph')
            return json.loads(manifest.read_text())

        contract = sync()
        assert all(p['Configurations'][0]['ReferenceBoundary'] for p in contract['Projects'].values())

        def build(hits, cache='cache', value='2', target='Build'):
            for project in root.glob('P*'):
                shutil.rmtree(project / 'bin', ignore_errors=True)
                shutil.rmtree(project / 'obj/Release', ignore_errors=True)
            run(DOTNET, RUNNER, 'action', root, manifest, report, work / cache, target)
            result = json.loads(report.read_text())
            assert result['hits'] == hits, result
            assembly = root / ('P2/bin/Release/net10.0/publish/P2.dll' if target == 'Publish' else 'P2/bin/Release/net10.0/P2.dll')
            assert run(DOTNET, assembly).stdout.strip() == value
            return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for project in root.glob('P*') for tree in ['bin/Release', 'obj/Release']
                    for p in (project / tree).rglob('*') if p.is_file() and not p.name.endswith('.AssemblyReference.cache')}

        build(0, value='1')
        (root / 'P0/Code.cs').write_text('/// <summary>Changed documentation</summary>\npublic class P0 { public static int Value() => 2; }')
        outputs = build(2)
        assert outputs == build(0, cache='body-control')
        assert 'Changed documentation' in (root / 'P2/bin/Release/net10.0/P0.xml').read_text()
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; public static int Extra() => 3; }')
        outputs = build(0 if transitive else 1)
        assert outputs == build(0, cache='api-control')
        (root / 'P1/Code.cs').write_text('public class P1 { public static int Value() => P0.Value(); public static int Extra() => 4; }')
        build(1)
        build(0, target='Publish')
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 3; public static int Extra() => 3; }')
        outputs = build(2, target='Publish', value='3')
        assert outputs == build(0, target='Publish', value='3', cache='publish-control')
        # Removing an optional dependency output must miss, not replay an old copy.
        project = root / 'P0/P0.csproj'
        original = project.read_text()
        project.write_text(original.replace('</Project>', '<PropertyGroup><GenerateDocumentationFile>false</GenerateDocumentationFile></PropertyGroup></Project>'))
        assert 'Graph definition changed' in run(DOTNET, RUNNER, 'inspect', root, manifest, report, success=False).stderr
        sync()
        build(0, value='3')
        assert not (root / 'P2/bin/Release/net10.0/P0.xml').exists()
        project.write_text(original)
        sync()
        build(2, value='3')
        assert (root / 'P2/bin/Release/net10.0/P0.xml').is_file()
        # Content can affect consumers independently of a reference assembly.
        project.write_text(project.read_text().replace('</Project>', '<ItemGroup><None Update="data.txt" CopyToOutputDirectory="PreserveNewest" /></ItemGroup></Project>'))
        (root / 'P0/data.txt').write_text('first')
        contract = sync()
        assert not contract['Projects']['P2/P2.csproj']['Configurations'][0]['ReferenceBoundary']
        build(0, value='3')
        (root / 'P0/data.txt').write_text('second')
        build(0, value='3')
        assert (root / 'P2/bin/Release/net10.0/data.txt').read_text() == 'second'
        print(f'PASS: transitive={transitive}, body/API/propagated API, XML copies, publish, content fallback')


if __name__ == '__main__':
    qualify(False)
    qualify(True)
