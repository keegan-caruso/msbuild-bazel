"""Qualify the complete runtime suite graph on a supported Bazel baseline.

Fresh seed, retained-worker edit/failure controls, raw parity and SDK-absent
execution are correctness checks. This controller does not score build timings.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

from runtime_full_source import capture_compiled_products, validate_raw_contract

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('raw_results', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--version', choices=['8.8.0', '9.2.0'], required=True)
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    root, raw, results, base = [p.resolve() for p in [args.workspace, args.raw_results, args.results, args.output_base]]
    assert not base.exists(), 'Compatibility requires a fresh output base'
    assert not results.is_relative_to(root) and not results.is_relative_to(raw)
    results.mkdir(parents=True, exist_ok=False)
    contract = json.loads((root / 'graph.generated.json').read_text())
    validate_raw_contract(contract, raw)
    nodes = [v for p in contract['Projects'].values() for v in p.get('Configurations') or [p]]
    assert len(nodes) == 543 and sum(bool(v['OutputDirectories'] or v.get('OutputFiles')) for v in nodes) == 481
    suite = json.loads((root / 'suite.json').read_text())
    assert len(suite['tests']) == 8 and contract['SdkVersion'] == '10.0.400'
    environment = dict(os.environ, USE_BAZEL_VERSION=args.version)
    for key in ['RULES_MSBUILD_PROJECT_CACHE_URL', 'RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN',
                'RULES_MSBUILD_GRAPH_PROFILE', 'RULES_MSBUILD_GRAPH_EVALUATION_PROFILE']:
        environment.pop(key, None)
    bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(base)]

    def invoke(command, name):
        with (results / (name + '.log')).open('w') as log:
            subprocess.run(command, cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)

    try:
        invoke(bazel + ['test', '//:runtime_suites', '--jobs=1', '--local_test_jobs=1',
            '--strategy=MSBuildGraph=worker', '--spawn_strategy=linux-sandbox',
            # NativeBuild provides its own declared filesystem/network namespace.
            '--strategy=RuntimeNative=standalone', '--worker_sandboxing',
            '--worker_max_instances=MSBuildGraph=1', '--disk_cache=', '--remote_cache=',
            '--test_output=errors', '--noshow_progress'], 'seed')
        report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
        assert (report['hits'], report['misses']) == (0, 481), report
        assert report['preparedRestore'] and report['readOnlyPreparedPackages']
        graph = capture_compiled_products(root / 'bazel-bin/graph.graph/workspace', contract)
        original = capture_compiled_products(raw / 'raw-workspace', contract)
        assert len(graph) == len(original) == 3622 and graph.keys() == original.keys()
        assert all(graph[p]['sha256'] == original[p]['sha256'] for p in graph), 'Seed raw byte parity'
        outcomes = Counter()
        for test in suite['tests']:
            label = test['target'].removeprefix('//:')
            for case in ET.parse(root / 'bazel-testlogs' / label / 'test.xml').getroot().findall('.//testcase'):
                outcomes['failed' if case.find('failure') is not None or case.find('error') is not None else
                         'skipped' if case.find('skipped') is not None else 'passed'] += 1
        assert outcomes == Counter(passed=118952, skipped=64), outcomes
        print(json.dumps(dict(stage='seed', compiled=481, products=3622, outcomes=outcomes)), flush=True)
        invoke([sys.executable, str(Path(__file__).with_name('runtime_suite_controls.py')), str(root), str(raw),
            str(results / 'controls'), '--output-base', str(base), '--version', args.version, '--all-suites'], 'controls')
        invoke([sys.executable, str(Path(__file__).with_name('runtime_suite_verify.py')), str(root), str(raw),
            str(results / 'parity'), '--sdk-absent'], 'parity')
        controls = json.loads((results / 'controls/summary.json').read_text())
        parity = json.loads((results / 'parity/summary.json').read_text())
        assert parity['compiledProducts'] == 3622 and len(parity['tests']) == 8
        assert all(t['sdkAbsent'] and t['reviewedNamesAndOutcomesMatch'] for t in parity['tests'])
        summary = dict(version=args.version, platform='linux-arm64', compiled=481, products=3622,
            outcomes=outcomes, controls=controls['rows'], parity=parity,
            scope='unscored complete eight-suite compatibility; native producers shared with raw')
        (results / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
        print('PASS: full runtime suite seed, replay, edits, failures, raw parity and SDK-absent execution', flush=True)
    finally:
        if base.exists():
            invoke(bazel + ['shutdown'], 'shutdown')


if __name__ == '__main__':
    main()
