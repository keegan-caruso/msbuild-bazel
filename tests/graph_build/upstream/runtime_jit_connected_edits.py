"""Qualify managed body/API and native-only edits across runtime -> JIT edges.

Use a disposable connected workspace from runtime_jit_public_prepare.py. Reports
are correctness controls, not paired timings. --recover executes an edited closure
on another machine with fresh Bazel state and the producer stopped.
"""
import argparse
from collections import Counter
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import tarfile
import uuid

from runtime_jit import inventory
from runtime_recovered_tests import graph_actions

ROOT = Path(__file__).resolve().parents[3]


def rewrite_version(source, output, token):
    with tarfile.open(source) as original, tarfile.open(output, 'w') as rewritten:
        seen = set()
        for member in original:
            assert member.name not in seen
            seen.add(member.name)
            if member.name == 'artifacts/obj/_version.c':
                body = original.extractfile(member).read()
                assert body.count(b'@Commit:') == 1
                body = body.replace(b'@Commit:', token.encode() + b' @Commit:')
                member.size = len(body)
                rewritten.addfile(member, io.BytesIO(body))
            else:
                rewritten.addfile(member, original.extractfile(member) if member.isfile() else None)
        assert 'artifacts/obj/_version.c' in seen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prepared', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--host-space-path', type=Path, required=True)
    parser.add_argument('--case', choices=['body', 'api', 'native'])
    parser.add_argument('--recover', type=Path)
    parser.add_argument('--close-api', type=Path, help='close the edited API source inputs for independent recovery')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    prepared, results = args.prepared.resolve(), args.results.resolve()
    root, source = prepared / 'workspace', prepared / 'source_runtime'
    metadata = json.loads((root / 'jit-public.json').read_text())
    assert metadata['sourceProducer'] and len(metadata['cases']) == 6
    expected = json.loads(args.recover.read_text()) if args.recover else None
    if expected:
        assert expected['machine'] != socket.gethostname() and expected['workspace'] != str(root)
        assert not args.output_base.exists()
    results.mkdir(parents=True, exist_ok=False)
    endpoint = os.environ['RULES_MSBUILD_PROJECT_CACHE_URL']
    command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(args.output_base.resolve()), 'test', '//:jit_tests',
        '--jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1',
        '--strategy=RuntimeNative=standalone', '--disk_cache=', '--remote_cache=' + endpoint, '--remote_cache_async=false',
        '--remote_download_outputs=all', '--remote_upload_local_results=' + str(not expected).lower(),
        '--nocache_test_results', '--test_output=all', '--lockfile_mode=off', '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + endpoint]
    edit = json.loads((Path(__file__).with_name('runtime_source_host_edit.json')).read_text())
    paths = [source / edit['implementation'], source / edit['reference']]
    originals = {path: path.read_bytes() for path in paths}
    native = source / 'native_support/source.tar'
    saved_native = native.with_suffix('.edit-save')
    assert not saved_native.exists()
    rows = []

    def run(label):
        subprocess.run(['fstrim', '/'], capture_output=True, check=True)
        stat = os.statvfs(args.host_space_path)
        assert stat.f_bavail * stat.f_frsize >= 12 * 1024**3, 'Insufficient physical host disk headroom'
        events, execution = results / (label + '.bep'), results / (label + '.execution.json')
        with (results / (label + '.log')).open('w') as log:
            subprocess.run(command + ['--build_event_json_file=' + str(events), '--execution_log_json_file=' + str(execution)],
                cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
        records = [json.loads(line) for line in events.read_text().splitlines()]
        tests = [event for event in records if 'testResult' in event]
        assert {event['id']['testResult']['label'] for event in tests} == {'//:' + case['name'] for case in metadata['cases']}
        assert Counter(event['testResult']['status'] for event in tests) == Counter(PASSED=6)
        assert all(not event['testResult'].get('cachedLocally') and not event['testResult'].get('executionInfo', {}).get('cachedRemotely') for event in tests)
        actions = graph_actions(execution, ['MSBuildGraph', 'MSBuildGraphRestore', 'RuntimeNative'])
        (results / (label + '-actions.json')).write_text(json.dumps(actions, indent=2) + '\n')
        execution.unlink()
        ran = [action for action in actions if not action.get('cacheHit')]
        source_graph = [action for action in ran if any(path.endswith('/external/jit_source_runtime+/graph.graph') for path in action['listedOutputs'])]
        jit_graph = [action for action in ran if action['mnemonic'] == 'MSBuildGraph' and any(path.endswith('/graph.graph') and '/external/' not in path for path in action['listedOutputs'])]
        native_actions = [action for action in ran if action['mnemonic'] == 'RuntimeNative']
        restore = [action for action in ran if action['mnemonic'] == 'MSBuildGraphRestore']
        output = root / 'bazel-bin/external/jit_source_runtime+'
        source_report = json.loads((output / 'graph.graph/report.json').read_text())
        jit_report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
        row = dict(case=label, executed=6, sourceMisses=source_report['misses'] if source_graph else None,
            jitMisses=jit_report['misses'] if jit_graph else None, graphExecutions=len([action for action in ran if action['mnemonic'] == 'MSBuildGraph']),
            nativeExecutions=len(native_actions), restoreExecutions=len(restore),
            sourceHost=inventory(output / 'core_root.layout'), sourceReferences=inventory(output / 'references/net10.0'),
            outputs=inventory(root / 'bazel-bin/graph.graph/workspace'))
        assert row['sourceHost'] and row['sourceReferences']
        if label in ['body', 'api']:
            assert len(source_graph) == 1 and row['sourceMisses'] == edit['expectedMisses'][label], row['sourceMisses']
            assert not native_actions, ran
            if label == 'body':
                assert not restore, ran
            else:
                assert len(restore) == 1 and any(path.endswith('/graph_restore.restore') and '/external/' not in path for path in restore[0]['listedOutputs']), restore
            assert row['sourceHost']['System.IO.Pipelines.dll'] != baseline['sourceHost']['System.IO.Pipelines.dll']
            if label == 'body':
                assert not jit_graph and row['sourceReferences'] == baseline['sourceReferences'], ran
                assert row['outputs'] == baseline['outputs']
            else:
                assert row['sourceReferences'] != baseline['sourceReferences']
                assert len(jit_graph) == 1 and row['jitMisses'] == 9, row['jitMisses']
        elif label == 'native':
            assert len(native_actions) == 1 and not source_graph and not jit_graph and not restore, ran
            assert any(path.endswith('/native_support/runtime.generated/runtime.tar') for path in native_actions[0]['listedOutputs'])
            assert row['outputs'] == baseline['outputs'] and row['sourceReferences'] == baseline['sourceReferences']
            assert token.encode() in (output / 'core_root.layout/libSystem.Native.so').read_bytes()
            assert {name for name in row['sourceHost'] if row['sourceHost'][name] != baseline['sourceHost'][name]} == {'libSystem.Native.so'}
        elif label.endswith('-restored'):
            assert not ran, ran
            assert all(row[key] == baseline[key] for key in ['outputs', 'sourceHost', 'sourceReferences'])
        elif expected:
            assert actions and all(action['cacheHit'] and action['runner'] == 'remote cache hit' for action in actions), actions
            assert all(row[key] == expected[key] for key in ['outputs', 'sourceHost', 'sourceReferences'])
        rows.append(row)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps({key: value for key, value in row.items() if key not in ['outputs', 'sourceHost', 'sourceReferences']}), flush=True)
        return row

    if expected:
        run('edited-recovery')
        return
    baseline = run('baseline')
    token = 'connected-' + uuid.uuid4().hex
    try:
        for case in ([args.case] if args.case else ['body', 'api', 'native']):
            if case == 'body':
                anchor = edit['bodyAnchor'].encode()
                assert originals[paths[0]].count(anchor) == 1
                paths[0].write_bytes(originals[paths[0]].replace(anchor, anchor + b'\n            GC.KeepAlive("' + token.encode() + b'");'))
            elif case == 'api':
                for path, key in zip(paths, ['implementationAnchor', 'referenceAnchor']):
                    anchor = edit[key].encode()
                    assert originals[path].count(anchor) == 1
                    path.write_bytes(originals[path].replace(anchor, anchor + b'\n        public const int ConnectedApiProbe = ' + str(100000 + int(token[-8:-2], 16)).encode() + b';'))
            else:
                native.rename(saved_native)
                rewrite_version(saved_native, native, token)
            row = run(case)
            if case == 'api' and args.close_api:
                row.update(machine=socket.gethostname(), workspace=str(root), sourceDigests=metadata['sourceDigests'])
                seed = results / 'edited-seed.json'
                seed.write_text(json.dumps(row, indent=2) + '\n')
                subprocess.run(['python3', str(Path(__file__).with_name('runtime_jit_public_consumer.py')),
                    str(prepared), str(seed), str(args.close_api)], check=True)
            for path, content in originals.items():
                path.write_bytes(content)
            if saved_native.exists():
                native.unlink()
                saved_native.rename(native)
            run(case + '-restored')
    finally:
        for path, content in originals.items():
            path.write_bytes(content)
        if saved_native.exists():
            native.unlink(missing_ok=True)
            saved_native.rename(native)
    print('PASS: connected managed/native edits, selective work, actual JIT execution and exact restoration', flush=True)


if __name__ == '__main__':
    main()
