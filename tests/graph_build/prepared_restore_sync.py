"""Graph sync emits a complete opt-in Restore contract and a small facade."""

import json
from pathlib import Path
import tempfile

from qualify import DOTNET, ROOT, SDK, fixture, run

SYNC = ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll'


def main():
    with tempfile.TemporaryDirectory(prefix='graph-restore-sync-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        fixture(root)
        (root / 'restore.settings').write_text('declared Restore setting')
        mapping = base / 'mapping.json'
        value = {'projectDefaults': {'preparedRestore': True, 'restoreInputs': ['restore.settings']}}
        mapping.write_text(json.dumps(value))
        command = [DOTNET, SYNC, root, SDK / 'sdk/10.0.400', 'P2/P2.csproj', '--mappings', mapping]
        run(*command)
        contract = json.loads((root / 'graph.generated.json').read_text())
        prepared = contract['Restore']
        assert set(contract['DefinitionDigests']) <= set(prepared['Inputs'])
        assert 'restore.settings' in prepared['Inputs'] and 'restore.settings' in contract['SharedInputs']
        assert not any(path.endswith('.cs') for path in prepared['Inputs'])
        assert len(prepared['Outputs']) == 15, prepared
        text = (root / 'graph.generated.bzl').read_text()
        assert 'msbuild_graph_restore(' in text and 'restore = ":" + name + "_restore"' in text
        section = text.split('msbuild_graph_restore(', 1)[1].split('    msbuild_graph(', 1)[0]
        assert 'Code.cs' not in section and 'restore.settings' in section
        run(*command, '--check')
        value['projects'] = {'P0/P0.csproj': {'preparedRestore': False, 'restoreInputs': []}}
        mapping.write_text(json.dumps(value))
        failure = run(*command, success=False)
        assert 'complete contract for every configuration' in failure.stderr, failure.stderr
        mapping.write_text('{}')
        run(*command)
        assert 'Restore' not in json.loads((root / 'graph.generated.json').read_text())
        assert 'msbuild_graph_restore' not in (root / 'graph.generated.bzl').read_text()
        print('PASS: generated Restore inputs/outputs, compiler-source exclusion, deterministic check, partial-contract rejection and default fallback')


if __name__ == '__main__':
    main()
