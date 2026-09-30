"""Benchmark lanes report retained state and restore scope explicitly."""
import json
from pathlib import Path
import sys
import tempfile
import threading

from qualify import ENV, ROOT, fixture, run
from remote import Cache, CacheServer


def main():
    server = CacheServer(('127.0.0.1', 0), Cache)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='graph-lanes-') as temporary:
            base = Path(temporary).resolve()
            for name, raw_state, cache_state in [('warm', 'warm', 'local'), ('cold', 'clean', 'empty'), ('recovery', 'clean', 'remote')]:
                root = base / name
                root.mkdir()
                contract = fixture(root)
                # Authored JSON can contain comments. Capture exact text for
                # diagnostics instead of assuming every .json is strict JSON.
                (root / 'P2/settings.json').write_text('{ // authored comment\n  "value": 1\n}\n')
                project = root / 'P2/P2.csproj'
                project.write_text(project.read_text().replace('</Project>',
                    '<ItemGroup><None Update="settings.json" CopyToOutputDirectory="Always" /></ItemGroup></Project>'))
                contract['Projects']['P2/P2.csproj']['Inputs'].append('P2/settings.json')
                manifest = base / (name + '.json')
                manifest.write_text(json.dumps(contract))
                edits = base / 'edits.json'
                edits.write_text(json.dumps([{'name': 'body', 'path': 'P0/Code.cs', 'before': '=> 1;', 'after': '=> 2;', 'sampleAfter': '=> 2${sample};'}]))
                if cache_state == 'remote':
                    ENV['RULES_MSBUILD_PROJECT_CACHE_URL'] = f'http://127.0.0.1:{server.server_port}'
                    ENV['RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN'] = 'fixture-token'
                results = base / (name + '-results')
                run(sys.executable, ROOT / 'tests/graph_build/upstream_edits.py', root, manifest, base / (name + '-cache'), edits, results,
                    '--samples', '2', '--raw-state', raw_state, '--cache-state', cache_state, '--raw-restore', '--profile')
                rows = json.loads((results / 'summary.json').read_text())
                assert len(rows) == 2 and rows[0]['name'] != rows[1]['name']
                for row in rows:
                    assert row['rawState'] == raw_state and row['cacheState'] == cache_state
                    assert row['rawRestoreSeconds'] > 0 and row['rawEndToEndSeconds'] > row['rawBuildSeconds']
                    assert not row['missing'] and not row['extra'] and not row['changed'], row
                    assert row['cached']['operations'] is not None
                    assert row['cached']['misses'] > 0, 'Each sample must contain a new edit'
            print('PASS: distinct samples, warm/local, cold/empty and fresh remote lanes; restore scope and output parity')
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
