"""Cache payloads share storage without sharing writable project output inodes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, RUNNER, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-shared-payloads-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        contract = fixture(root)
        payload = b'one payload, different project permissions\n'
        (root / 'shared.txt').write_bytes(payload)
        contract['SharedInputs'].append('shared.txt')
        for index in range(3):
            project = root / f'P{index}/P{index}.csproj'
            command = '' if os.name == 'nt' else f'<Exec Command="chmod {755 if index == 1 else 644} &quot;$(TargetDir)shared.txt&quot;" />'
            project.write_text(project.read_text().replace('</Project>',
                '<Target Name="SharedPayload" AfterTargets="Build"><Copy SourceFiles="../shared.txt" '
                'DestinationFiles="$(TargetDir)shared.txt" />' + command + '</Target></Project>'))
        manifest, report, cache = base / 'contract.json', base / 'report.json', base / 'cache'
        manifest.write_text(json.dumps(contract))
        def build(success=True, no_read=False):
            for project in contract['Projects'].values():
                for directory in project['OutputDirectories']:
                    shutil.rmtree(root / directory, ignore_errors=True)
            arguments = ['Build', 'no-read'] if no_read else []
            result = run(DOTNET, RUNNER, 'build', root, manifest, report, cache, *arguments, success=success)
            return json.loads(report.read_text()) if success else result.stderr
        assert build()['hits'] == 0
        digest = hashlib.sha256(payload).hexdigest()
        blob = cache / '.cas' / digest
        entries = [path for path in cache.glob('*/P*/bin/Release/net10.0/shared.txt')]
        assert len(entries) == 3 and blob.read_bytes() == payload, entries
        if os.name != 'nt':
            assert all(path.stat().st_ino == blob.stat().st_ino for path in entries)
        assert build()['hits'] == 3
        for index in range(3):
            output = root / f'P{index}/bin/Release/net10.0/shared.txt'
            assert output.read_bytes() == payload
            if os.name != 'nt':
                assert output.stat().st_ino != blob.stat().st_ino
                assert output.stat().st_mode & 0o777 == (0o755 if index == 1 else 0o644)
            output.write_bytes(b'consumer mutation')
        assert blob.read_bytes() == payload and all(path.read_bytes() == payload for path in entries)
        assert build()['hits'] == 3
        snapshot = next(cache.glob('*/manifest.json'))
        original = snapshot.read_bytes()
        conflicting = json.loads(original)
        conflicting['Targets'][0]['Name'] = 'ConflictingTarget'
        snapshot.write_text(json.dumps(conflicting))
        assert 'Conflicting graph snapshot' in build(success=False, no_read=True)
        assert not list(cache.glob('.staging-*'))
        snapshot.write_bytes(original)
        blob.write_bytes(b'corrupt shared payload')
        assert 'Corrupt graph snapshot' in build(success=False)
        assert not list((cache / '.cas').glob('*.pending-*'))
        print('PASS: deduplicated payload inodes, independent output bytes/modes, consumer mutation isolation, conflicting snapshot cleanup and corruption rejection')


if __name__ == '__main__':
    main()
