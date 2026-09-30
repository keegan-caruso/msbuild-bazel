"""Projects own individual files in a shared output directory."""

import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-output-files-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        for name in ['Library', 'App']:
            (root / name).mkdir()
            reference = '<ItemGroup><ProjectReference Include="../Library/Library.csproj" /></ItemGroup>' if name == 'App' else ''
            (root / name / f'{name}.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>' + reference + '</Project>')
            (root / name / 'Code.cs').write_text(f'public class {name} {{ public static int Value() => 1; }}')
        target = root / 'Directory.Build.targets'
        target.write_text('<Project><ItemGroup><GraphOutput Include="shared/$(AssemblyName).dll" Kind="published" /></ItemGroup><Target Name="SharedOutput" AfterTargets="Build"><Copy SourceFiles="$(TargetPath)" DestinationFiles="$(MSBuildThisFileDirectory)shared/$(AssemblyName).dll" /></Target></Project>')
        mapping = {'projectDefaults': {'outputFiles': ["@(GraphOutput->WithMetadataValue('Kind', 'published'));$(AbsentOutput)"], 'evaluationItems': ['GraphOutput'], 'documents': {'Directory.Build.targets': {
            'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'targets': ['SharedOutput'], 'tasks': [], 'inputs': []}}}}
        mapping['projectDefaults']['frameworkOverrides'] = {'net10.0': {'outputFiles': mapping['projectDefaults']['outputFiles']}}
        mapping['projectDefaults']['outputFiles'] = ['shared/wrong-framework.dll']
        mapping_path = root / 'mappings.json'
        mapping_path.write_text(json.dumps(mapping))
        sync = [DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root, SDK / 'sdk/10.0.400', 'App/App.csproj', '--graph', '--mappings', mapping_path]
        run(*sync)
        contract_path = root / 'graph.generated.json'
        contract = json.loads(contract_path.read_text())
        for name in ['App', 'Library']:
            config = contract['Projects'][f'{name}/{name}.csproj']['Configurations'][0]
            assert config['OutputFiles'] == [f'shared/{name}.dll'], config
            assert not config['ReferenceBoundary']
        report = base / 'report.json'
        cache = base / 'cache'
        command = [DOTNET, RUNNER, 'action', root, contract_path, report, cache]
        def clear():
            for name in ['Library', 'App']:
                for folder in ['bin', 'obj']:
                    shutil.rmtree(root / name / folder, ignore_errors=True)
            shutil.rmtree(root / 'shared', ignore_errors=True)
        def build(hits):
            clear()
            run(*command)
            assert json.loads(report.read_text())['hits'] == hits, report.read_text()
            for name in ['Library', 'App']:
                assert (root / f'shared/{name}.dll').read_bytes() == (root / name / f'bin/Release/net10.0/{name}.dll').read_bytes()
            return (root / 'shared/Library.dll').read_bytes()
        before = build(0)
        assert build(2) == before
        # An ownership index must still reject a cached file owned by another node.
        snapshot = next(path for path in cache.glob('*/manifest.json')
                        if 'App/bin/Release/net10.0/App.dll' in json.loads(path.read_text())['Files'])
        original_snapshot = snapshot.read_text()
        forged = json.loads(original_snapshot)
        forged['Files']['Library/bin/Release/net10.0/foreign.dll'] = next(iter(forged['Files'].values()))
        snapshot.write_text(json.dumps(forged))
        clear()
        assert 'Snapshot output escaped project ownership' in run(*command, success=False).stderr
        snapshot.write_text(original_snapshot)
        # Resolving real accesses still rejects output-directory symlinks.
        clear()
        outside = base / 'outside'
        outside.mkdir()
        (outside / 'App.dll').write_text('outside')
        (root / 'shared').symlink_to(outside, target_is_directory=True)
        assert 'Symlinks are not supported' in run(*command, success=False).stderr
        (root / 'shared').unlink()
        assert (outside / 'App.dll').read_text() == 'outside'
        assert build(2) == before
        (root / 'Library/Code.cs').write_text('public class Library { public static int Value() => 2; }')
        assert build(0) != before
        build(2)
        clear()
        (root / 'shared').mkdir()
        (root / 'shared/App.dll').write_text('old output')
        assert 'requires absent declared output files' in run(*command, success=False).stderr
        clear()
        for output, error in [('shared/Library.dll', 'Overlapping output file ownership'),
                              ('Library/bin/Release/net10.0/foreign.dll', 'Overlapping output file ownership'),
                              ('App/Code.cs', 'Output file overlaps a declared input'),
                              ('shared/missing.dll', 'Missing declared output file')]:
            changed = copy.deepcopy(contract)
            changed['Projects']['App/App.csproj']['Configurations'][0]['OutputFiles'] = [output]
            contract_path.write_text(json.dumps(changed))
            clear()
            assert error in run(*command, success=False).stderr, error
        print('PASS: shared output ownership, replay, edit invalidation, conflicts, input overlap and missing/preexisting output rejection')


if __name__ == '__main__':
    main()
