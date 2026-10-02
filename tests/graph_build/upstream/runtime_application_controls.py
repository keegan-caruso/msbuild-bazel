"""Qualify ordinary-app caching, runtime body edits and deliberate app failure."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output-base', type=Path, required=True, help='warm successful app/test base; retain its graph worker')
    parser.add_argument('--version', choices=['8.8.0', '9.2.0'], default='9.2.0')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    root, results = args.workspace.resolve(), args.results.resolve()
    results.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[3]
    bazel = [str(repo / 'scripts/bazel-launcher.sh'), '--output_base=' + str(args.output_base.resolve()),
             'test', '//:app_test', '--jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing',
             '--worker_max_instances=MSBuildGraph=1', '--disk_cache=', '--remote_cache=', '--test_output=errors', '--noshow_progress']
    environment = dict(os.environ, USE_BAZEL_VERSION=args.version)
    contract = json.loads((root / 'graph.generated.json').read_text())
    count = sum(bool(node['OutputDirectories'] or node.get('OutputFiles')) for project in contract['Projects'].values()
                for node in project.get('Configurations') or [project])
    assert count == 263, 'Use the reviewed combined ordinary-app graph'
    mutation = json.loads(Path(__file__).with_name('runtime_loaded_common_edit.json').read_text())
    implementation, app_source = root / mutation['implementation'], root / 'app/Program.cs'
    originals = {path: path.read_bytes() for path in [implementation, app_source]}
    rows = []
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    def binaries():
        host = root / 'bazel-bin/app_source_runtime.layout'
        return {str(path.relative_to(host)): digest(path) for path in host.rglob('*') if path.is_file()
                and (path.suffix in ['.dll', '.so'] or path.name == 'dotnet')}
    def run(label, success, cached, graph_actions):
        bep = results / (label + '.bep')
        with (results / (label + '.log')).open('w') as log:
            process = subprocess.run(bazel + ['--build_event_json_file=' + str(bep)], cwd=root,
                                     env=environment, stdout=log, stderr=subprocess.STDOUT)
        assert (process.returncode == 0) == success, label
        events = [json.loads(line) for line in bep.read_text().splitlines()]
        summary = next(event['buildMetrics']['actionSummary'] for event in events if 'buildMetrics' in event)
        actions = {item['mnemonic']: int(item.get('actionsExecuted', 0)) for item in summary.get('actionData', [])}
        assert actions.get('RuntimeNative', 0) == 0 and actions.get('MSBuildGraph', 0) == graph_actions, actions
        outcomes = [event['testResult'] for event in events if 'testResult' in event]
        assert len(outcomes) == 1 and bool(outcomes[0].get('cachedLocally', False)) == cached, outcomes
        assert outcomes[0]['status'] == ('PASSED' if success else 'FAILED'), outcomes
        row = dict(case=label, version=args.version, passed=success, cached=cached, graphActions=graph_actions, nativeActions=0,
                   appSha256=digest(root / 'bazel-bin/app_test.runtime/App.dll'), binaryHashes=binaries())
        if label in ['runtime-body', 'restored-runtime']:
            report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
            misses = mutation['expectedMisses']['body'] if label == 'runtime-body' else 0
            assert (report['hits'], report['misses']) == (count - misses, misses), report
            row.update(hits=report['hits'], misses=report['misses'])
        if label in ['app-failure', 'restored-app']:
            report = json.loads((root / 'bazel-bin/app_build.graph/report.json').read_text())
            expected = (0, 1) if label == 'app-failure' else (1, 0)
            assert (report['hits'], report['misses']) == expected, report
            row.update(hits=report['hits'], misses=report['misses'])
        rows.append(row)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps({key: value for key, value in row.items() if key != 'binaryHashes'}), flush=True)
        return row
    try:
        baseline = run('unchanged-cached', True, True, 0)
        anchor = mutation['bodyAnchor'].encode()
        assert originals[implementation].count(anchor) == 1
        implementation.write_bytes(originals[implementation].replace(anchor,
            anchor + b'\n            GC.KeepAlive("' + str(uuid.uuid4()).encode() + b'");'))
        edited = run('runtime-body', True, False, 1)
        assert edited['appSha256'] == baseline['appSha256'], 'Runtime body edit recompiled app'
        pipeline = 'shared/Microsoft.NETCore.App/10.0.0/System.IO.Pipelines.dll'
        assert edited['binaryHashes'][pipeline] != baseline['binaryHashes'][pipeline]
        implementation.write_bytes(originals[implementation])
        restored = run('restored-runtime', True, False, 1)
        assert restored['binaryHashes'] == baseline['binaryHashes'] and restored['appSha256'] == baseline['appSha256']
        anchor = b'// Ordinary framework APIs exercise managed and native source-built components.'
        assert originals[app_source].count(anchor) == 1
        app_source.write_bytes(originals[app_source].replace(anchor,
            anchor + b'\nif (args.Length >= 0) throw new InvalidOperationException("deliberate app failure ' + str(uuid.uuid4()).encode() + b'");'))
        failed = run('app-failure', False, False, 1)
        assert failed['appSha256'] != baseline['appSha256'] and failed['binaryHashes'] == baseline['binaryHashes']
        assert 'deliberate app failure' in (results / 'app-failure.log').read_text()
        app_source.write_bytes(originals[app_source])
        restored = run('restored-app', True, False, 1)
        assert restored['binaryHashes'] == baseline['binaryHashes'] and restored['appSha256'] == baseline['appSha256']
        print('PASS: runtime body invalidates test without app compilation; deliberate app failure and restoration', flush=True)
    finally:
        for path, content in originals.items():
            if path.read_bytes() != content:
                path.write_bytes(content)


if __name__ == '__main__':
    main()
