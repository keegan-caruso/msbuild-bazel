"""Qualify generated JIT graphs; reports and disposable inputs stay outside Git."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import time
import uuid

from runtime_jit import digest, inventory
from runtime_jit_prepare import CODE, ENTRY, PINNED, TEST_OUTPUT

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--raw', type=Path)
    parser.add_argument('--seed-report', type=Path)
    parser.add_argument('--host-space-path', type=Path, required=True)
    args = parser.parse_args()
    root, results = args.workspace.resolve(), args.results.resolve()
    results.mkdir(parents=True, exist_ok=False)
    for path, value in PINNED.items():
        assert digest(root / path) == value, path
    endpoint = os.environ['RULES_MSBUILD_PROJECT_CACHE_URL']
    command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(args.output_base.resolve()), 'test', '//:add1',
        '--jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1',
        '--disk_cache=', '--remote_cache=', '--nocache_test_results', '--test_output=all', '--lockfile_mode=off',
        '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + endpoint]
    rows = []

    def invoke(label, success=True):
        subprocess.run(['fstrim', '/'], check=True, capture_output=True)
        disk = os.statvfs(args.host_space_path)
        assert disk.f_bavail * disk.f_frsize >= 8 * 1024**3, 'Insufficient physical host disk headroom'
        events = results / (label + '.bep')
        start = time.monotonic()
        with (results / (label + '.log')).open('w') as log:
            outcome = subprocess.run(command + ['--build_event_json_file=' + str(events)], cwd=root, stdout=log, stderr=subprocess.STDOUT)
        assert (outcome.returncode == 0) == success, str(results / (label + '.log'))
        records = [json.loads(line) for line in events.read_text().splitlines()]
        tests = [event['testResult'] for event in records if 'testResult' in event]
        if success or label == 'failure':
            assert len(tests) == 1
            assert tests[0]['status'] == ('PASSED' if success else 'FAILED'), tests
            assert not tests[0].get('cachedLocally') and not tests[0].get('executionInfo', {}).get('cachedRemotely'), tests
        row = dict(case=label, seconds=time.monotonic() - start, success=success, executed=len(tests))
        if success:
            graph = root / 'bazel-bin/graph.graph'
            report = json.loads((graph / 'report.json').read_text())
            row.update(hits=report['hits'], misses=report['misses'], outputs=inventory(graph / 'workspace'),
                sourceHost=inventory(root / 'bazel-bin/core_root.layout'))
        rows.append(row)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps({k: v for k, v in row.items() if k not in ['outputs', 'sourceHost']}), flush=True)
        return row

    seed = invoke('recovery' if args.seed_report else 'seed')
    if args.seed_report:
        expected = json.loads(args.seed_report.read_text())
        assert (seed['hits'], seed['misses']) == (3, 0)
        for key in ['outputs', 'sourceHost']:
            assert seed[key] == expected[key], key
        print('PASS: independent public JIT recovery and actual source-runtime execution', flush=True)
        return
    assert args.raw
    compiled = [path for path in seed['outputs'] if path.endswith(('.dll', '.pdb'))]
    assert len(compiled) == 12, compiled
    for path in compiled:
        assert digest(args.raw / path) == seed['outputs'][path]['sha256'], path
    targeting = next((root / 'bazel-bin/external').glob('*/targeting/TargetingPack'))
    deployed = inventory(targeting)
    raw_deployed = inventory(args.raw / 'artifacts/TargetingPack')
    assert deployed.keys() == raw_deployed.keys(), 'Bootstrap product inventory differs'
    for path in deployed:
        assert deployed[path]['sha256'] == raw_deployed[path]['sha256'], path
    seed.update(comparedCompiledFiles=len(compiled), bootstrapOutputs=deployed)
    (results / 'seed.json').write_text(json.dumps(seed, indent=2) + '\n')
    source = root / CODE
    original = source.read_bytes()
    generator = root / 'src/tests/Common/XUnitWrapperGenerator/XUnitWrapperGenerator.cs'
    original_generator = generator.read_bytes()
    generated = root / 'graph.generated.bzl'
    original_generated = generated.read_text()
    try:
        source.write_bytes(original.replace(b'return x+1;', b'return unchecked(x+1);') + ('\n// Body token: ' + uuid.uuid4().hex + '\n').encode())
        body = invoke('body')
        assert (body['hits'], body['misses']) == (2, 1)
        assert body['outputs'][TEST_OUTPUT + '/Add1_ro.dll'] != seed['outputs'][TEST_OUTPUT + '/Add1_ro.dll']
        source.write_bytes(original.replace(b'return x+1;', b'return x+2;'))
        invoke('failure', False)
        assert 'Expected exit code 100, received 101' in (results / 'failure.log').read_text()
        source.write_bytes(original)
        assert invoke('restored')['outputs'] == seed['outputs']
        generator.write_bytes(original_generator + ('\ninternal static class QualificationGeneratorInput_' + uuid.uuid4().hex + ' {}\n').encode())
        changed = invoke('generator')
        assert (changed['hits'], changed['misses']) == (1, 2)
        generator.write_bytes(original_generator)
        assert invoke('generator-restored')['outputs'] == seed['outputs']
        bindings = re.findall(r'"[^"]+":"artifacts/bin/ref/net10.0"', original_generated)
        assert bindings and len(set(bindings)) == 1
        binding = bindings[0]
        generated.write_text(original_generated.replace(',' + binding, '').replace(binding + ',', '').replace(binding, ''))
        invoke('missing-references', False)
    finally:
        source.write_bytes(original)
        generator.write_bytes(original_generator)
        generated.write_text(original_generated)
    print('PASS: public update/sync, raw parity, edits, generator invalidation and exit semantics', flush=True)


if __name__ == '__main__':
    main()
