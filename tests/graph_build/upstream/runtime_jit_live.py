"""Execute JIT tests with live source-runtime edges and independent cache recovery.

The public prepared workflow consumes no products archive. A fixture-only Bazel
input forces JIT project recovery while retaining normal caching of source-runtime
producers. Reports distinguish cached producer counters from current execution.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import socket
import subprocess
import uuid

from runtime_jit import inventory
from runtime_recovered_tests import graph_actions

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prepared', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--bounded-seed', type=Path, help='raw-qualified archive control for byte parity')
    parser.add_argument('--seed-report', type=Path, help='independent live producer evidence')
    parser.add_argument('--host-space-path', type=Path, required=True)
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    prepared, results = args.prepared.resolve(), args.results.resolve()
    root = prepared / 'workspace'
    metadata = json.loads((root / 'jit-public.json').read_text())
    assert metadata['sourceProducer'] and not (root / 'source-products.tar.gz').exists()
    expected = json.loads(args.seed_report.read_text()) if args.seed_report else None
    if expected:
        assert expected['machine'] != socket.gethostname() and expected['workspace'] != str(root)
        assert not args.output_base.exists(), 'Independent recovery needs a fresh output base'
    else:
        assert args.bounded_seed, 'Producer requires raw-qualified bounded evidence'
    results.mkdir(parents=True, exist_ok=False)
    generated = root / 'graph.generated.bzl'
    original = generated.read_text()
    prefix, action = original.split('    msbuild_graph(\n', 1)
    marker = root / 'jit-recovery-request.txt'
    assert not marker.exists() and marker.name not in original
    generated.write_text(prefix + '    msbuild_graph(\n' + action.replace('        srcs = [', '        srcs = ["jit-recovery-request.txt",', 1))
    marker.write_text('jit-live-seed')
    endpoint = os.environ['RULES_MSBUILD_PROJECT_CACHE_URL']
    command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(args.output_base.resolve())]
    options = ['--jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing',
        '--worker_max_instances=MSBuildGraph=1', '--strategy=RuntimeNative=standalone',
        '--disk_cache=', '--remote_cache=' + endpoint, '--remote_cache_async=false',
        '--remote_download_outputs=all', '--remote_upload_local_results=' + str(not expected).lower(),
        '--nocache_test_results', '--test_output=all', '--lockfile_mode=off',
        '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + endpoint]
    rows = []

    def invoke(label, whole=False):
        subprocess.run(['fstrim', '/'], check=True, capture_output=True)
        disk = os.statvfs(args.host_space_path)
        assert disk.f_bavail * disk.f_frsize >= 12 * 1024**3, 'Insufficient physical host disk headroom'
        events, execution = results / (label + '.bep'), results / (label + '.execution.json')
        with (results / (label + '.log')).open('w') as log:
            subprocess.run(command + ['test', '//:jit_tests', *options,
                '--build_event_json_file=' + str(events), '--execution_log_json_file=' + str(execution)],
                cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
        records = [json.loads(line) for line in events.read_text().splitlines()]
        tests = [event for event in records if 'testResult' in event]
        assert {event['id']['testResult']['label'] for event in tests} == {'//:' + case['name'] for case in metadata['cases']}
        assert Counter(event['testResult']['status'] for event in tests) == Counter(PASSED=len(metadata['cases']))
        assert all(not event['testResult'].get('cachedLocally') and not event['testResult'].get('executionInfo', {}).get('cachedRemotely') for event in tests)
        actions = graph_actions(execution, ['MSBuildGraph', 'MSBuildGraphRestore', 'RuntimeNative'])
        (results / (label + '-actions.json')).write_text(json.dumps(actions, indent=2) + '\n')
        report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
        source_output = root / 'bazel-bin/external/jit_source_runtime+'
        outputs = inventory(root / 'bazel-bin/graph.graph/workspace')
        host = inventory(source_output / 'core_root.layout')
        references = inventory(source_output / 'references/net10.0')
        assert host and references and 'corerun' in host
        row = dict(case=label, executed=len(tests), outputs=outputs, sourceHost=host, sourceReferences=references,
            hits=None if whole else report['hits'], misses=None if whole else report['misses'],
            reportOrigin='producer-cache' if whole else 'current-action')
        if expected:
            for key in ['outputs', 'sourceHost', 'sourceReferences']:
                assert row[key] == expected[key], key
            if whole:
                native = {row['producer'] for row in json.loads((prepared / 'source_runtime/application.json').read_text())['native'].values()}
                native_actions = [action for action in actions if action['mnemonic'] == 'RuntimeNative']
                assert len(native_actions) == len(native) == 5, native_actions
                for name in native:
                    assert any(any(path.endswith('/' + name + '/runtime.generated/runtime.tar') for path in action['listedOutputs']) for action in native_actions), name
                assert any(action['mnemonic'] == 'MSBuildGraph' and any(path.endswith('/external/jit_source_runtime+/graph.graph') for path in action['listedOutputs']) for action in actions), actions
                assert any(action['mnemonic'] == 'MSBuildGraphRestore' for action in actions), actions
                assert actions and all(action['cacheHit'] and action['runner'] == 'remote cache hit' for action in actions), actions
            else:
                executed = [action for action in actions if not action.get('cacheHit')]
                assert len(executed) == 1 and executed[0]['mnemonic'] == 'MSBuildGraph', executed
                assert any(path.endswith('/graph.graph') and '/external/' not in path for path in executed[0]['listedOutputs']), executed
                assert (report['hits'], report['misses']) == (expected['nodeCount'], 0), report
        else:
            bounded = json.loads(args.bounded_seed.read_text())
            assert outputs == bounded['outputs'] and host == bounded['sourceHost'], 'Live producer differs from raw-qualified products'
            row.update(nodeCount=bounded['nodeCount'], machine=socket.gethostname(), workspace=str(root), sourceDigests=metadata['sourceDigests'])
            (results / 'seed.json').write_text(json.dumps(row, indent=2) + '\n')
        rows.append(row)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        execution.unlink()
        print(json.dumps({key: value for key, value in row.items() if key not in ['outputs', 'sourceHost', 'sourceReferences', 'sourceDigests']}), flush=True)

    try:
        invoke('whole' if expected else 'seed', whole=bool(expected))
        if expected:
            marker.write_text(uuid.uuid4().hex)
            invoke('project-recovery')
    finally:
        generated.write_text(original)
        marker.unlink()
    print('PASS: declared source-runtime edges and actual JIT execution', flush=True)


if __name__ == '__main__':
    main()
