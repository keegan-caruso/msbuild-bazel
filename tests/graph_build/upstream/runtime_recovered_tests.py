"""Seed and independently execute recovered runtime suites with current graph code.

Requires the qualified public 481-compilation runtime workspace and a healthy
Linux ARM64 machine. Producer publishes complete actions/project snapshots;
consumer executes all tests, then forces project recovery and executes them again.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

from runtime_suite_verify import proofs

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests/runtime'))
from case_names import normalize


def graph_actions(path):
    # Keep only graph/cache summaries. Decode at offsets, avoiding repeated
    # copies of the large log and retention of every SDK/test input inventory.
    text, decoder, selected, position = path.read_text(), json.JSONDecoder(), [], 0
    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if position == len(text):
            break
        row, position = decoder.raw_decode(text, position)
        if row.get('mnemonic') in ['MSBuildGraph', 'MSBuildGraphRestore']:
            selected.append({key: row.get(key) for key in ['mnemonic', 'targetLabel', 'listedOutputs', 'cacheHit', 'runner', 'status', 'metrics']})
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--cache-url', required=True)
    parser.add_argument('--phase', choices=['producer', 'consumer'], required=True)
    parser.add_argument('--seed-report', type=Path)
    parser.add_argument('--host-space-path', type=Path, required=True)
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert bool(args.seed_report) == (args.phase == 'consumer')
    root, results = args.workspace.resolve(), args.results.resolve()
    assert not args.output_base.exists()
    results.mkdir(parents=True, exist_ok=False)
    contract = json.loads((root / 'graph.generated.json').read_text())
    nodes = [node for project in contract['Projects'].values() for node in project['Configurations']]
    assert len(nodes) == 543
    suite = json.loads((root / 'suite.json').read_text())
    assert len(suite['tests']) == 8
    targets = {row['target'] for row in suite['tests']} | {'//:app_test'}
    seed = json.loads(args.seed_report.read_text()) if args.seed_report else None
    if seed:
        assert seed['machine'] != socket.gethostname() and seed['workspace'] != str(root)
        assert seed['contractSha256'] == hashlib.sha256((root / 'graph.generated.json').read_bytes()).hexdigest()
    generated = root / 'graph.generated.bzl'
    original = generated.read_text()
    prefix, action = original.split('    msbuild_graph(\n', 1)
    assert 'suite-recovery-request.txt' not in original
    action = action.replace('        srcs = [', '        srcs = ["suite-recovery-request.txt",', 1)
    generated.write_text(prefix + '    msbuild_graph(\n' + action)
    marker = root / 'suite-recovery-request.txt'
    marker.write_text('suite-recovery-seed')
    command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(args.output_base.resolve())]
    options = ['--jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1',
        '--local_test_jobs=1', '--disk_cache=', '--remote_cache=' + args.cache_url, '--remote_cache_async=false',
        '--remote_download_outputs=all', '--remote_upload_local_results=' + str(args.phase == 'producer').lower(),
        '--nocache_test_results', '--test_output=errors', '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + args.cache_url]
    rows = []

    def run(label, whole=False):
        subprocess.run(['fstrim', '/'], check=True, capture_output=True)
        disk = os.statvfs(args.host_space_path)
        assert disk.f_bavail * disk.f_frsize >= 12 * 1024**3, 'Insufficient physical host disk headroom'
        events, execution = results / (label + '.bep'), results / (label + '.execution.json')
        start = time.monotonic()
        with (results / (label + '.log')).open('w') as log:
            subprocess.run(command + ['test', *sorted(targets), *options, '--build_event_json_file=' + str(events),
                '--execution_log_json_file=' + str(execution)], cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
        records = [json.loads(line) for line in events.read_text().splitlines()]
        tests = [event for event in records if 'testResult' in event]
        assert len(tests) == 9 and {event['id']['testResult']['label'] for event in tests} == targets
        assert all(event['testResult']['status'] == 'PASSED' and not event['testResult'].get('cachedLocally') and
            not event['testResult'].get('executionInfo', {}).get('cachedRemotely') for event in tests), tests
        graph = root / 'bazel-bin/graph.graph'
        report = json.loads((graph / 'report.json').read_text())
        actions = graph_actions(execution)
        (results / (label + '-actions.json')).write_text(json.dumps(actions, indent=2) + '\n')
        main = next(row for row in actions if row.get('mnemonic') == 'MSBuildGraph' and any(path.endswith('/graph.graph') for path in row['listedOutputs']))
        if args.phase == 'consumer':
            assert bool(main.get('cacheHit')) == whole, main
            if whole:
                restore = next(row for row in actions if row['mnemonic'] == 'MSBuildGraphRestore' and row['targetLabel'] == '//:graph_restore')
                assert restore['cacheHit'] and restore['runner'] == 'remote cache hit', restore
            if not whole:
                assert (report['hits'], report['misses']) == (481, 0), report
        else:
            assert report['hits'] + report['misses'] == 481
        directories = {path for node in nodes for path in node['OutputDirectories']}
        outputs = {path for node in nodes for path in node.get('OutputFiles', [])}
        disposable = {directory + '/' + Path(project).name + '.GenerateResource.cache'
            for project, declaration in contract['Projects'].items() for node in declaration['Configurations']
            for directory in node['OutputDirectories'] if directory.startswith('artifacts/obj/')}
        paths = {graph / 'workspace' / path for path in outputs} | {p for directory in directories for p in (graph / 'workspace' / directory).rglob('*')}
        files = {str(p.relative_to(graph / 'workspace')): dict(sha256=hashlib.sha256(p.read_bytes()).hexdigest(), mode=p.stat().st_mode & 0o777)
            for p in paths if p.is_file() and not p.name.endswith('.AssemblyReference.cache') and
            (str(p.relative_to(graph / 'workspace')) not in disposable or str(p.relative_to(graph / 'workspace')) in outputs)}
        outcomes, signatures = Counter(), {}
        observations = 0
        application = json.loads((root / 'application.json').read_text())
        expected_runtime = {}
        for scope in ['managed', 'private']:
            for name, producer in application.get(scope, {}).items():
                expected_runtime.setdefault(name, set()).add(hashlib.sha256((graph / 'workspace' / producer['path']).read_bytes()).hexdigest().upper())
        for name, producer in application['native'].items():
            expected_runtime.setdefault(name, set()).add(hashlib.sha256((root / 'bazel-bin' / producer['producer'] / 'runtime.generated' / name).read_bytes()).hexdigest().upper())
        required = {'System.Private.CoreLib.dll', 'libcoreclr.so', 'libclrjit.so', 'dotnet', 'libhostfxr.so', 'libhostpolicy.so'}
        for selection in suite['tests']:
            folder = root / 'bazel-testlogs' / selection['target'].removeprefix('//:')
            cases = Counter()
            for case in ET.parse(folder / 'test.xml').getroot().findall('.//testcase'):
                outcome = 'failed' if case.find('failure') is not None or case.find('error') is not None else 'skipped' if case.find('skipped') is not None else 'passed'
                cases[case.get('name'), outcome] += 1
                outcomes[outcome] += 1
            canonical = sorted((name, outcome, count) for (name, outcome), count in normalize(cases).items())
            signatures[selection['target']] = dict(cases=sum(cases.values()), sha256=hashlib.sha256(json.dumps(canonical).encode()).hexdigest())
            observed = proofs(folder / 'test.outputs')
            assert observed, selection['target']
            for proof in observed:
                assert required <= proof['files'].keys(), proof
                for name, digest in proof['files'].items():
                    if name in expected_runtime:
                        assert digest['sha256'] in expected_runtime[name], (selection['target'], name)
                observations += 1
        assert outcomes == Counter(passed=118952, skipped=64), outcomes
        if seed:
            assert files == seed['files'] and signatures == seed['signatures'], 'Recovered products/outcomes differ'
        row = dict(case=label, seconds=time.monotonic()-start, machine=socket.gethostname(), workspace=str(root),
            contractSha256=hashlib.sha256((root / 'graph.generated.json').read_bytes()).hexdigest(),
            executedTests=9, outcomes=dict(outcomes), runtimeObservations=observations, wholeActionHit=bool(main.get('cacheHit')),
            reportOrigin='producer-cache' if whole else 'executed',
            hits=None if whole else report['hits'], misses=None if whole else report['misses'], files=files, signatures=signatures)
        rows.append(row)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        if args.phase == 'producer':
            (results / 'seed.json').write_text(json.dumps(row, indent=2) + '\n')
        execution.unlink()
        print(json.dumps({k:v for k,v in row.items() if k not in ['files','signatures']}), flush=True)

    try:
        run('seed' if args.phase == 'producer' else 'whole-recovery', whole=args.phase == 'consumer')
        if args.phase == 'consumer':
            marker.write_text(uuid.uuid4().hex)
            run('project-recovery')
    finally:
        generated.write_text(original)
        marker.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
