"""Seed and independently execute recovered runtime suites with current graph code.

Requires the qualified public 481-compilation runtime workspace and a healthy
Linux ARM64 machine. Producer publishes complete actions/project snapshots;
consumer executes all tests, then forces project recovery and executes them again.
Use --demo for a whole-action recovery followed by separately timed actual tests.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET

from runtime_suite_verify import proofs

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests/runtime'))
from case_names import normalize


def graph_actions(path, mnemonics=('MSBuildGraph', 'MSBuildGraphRestore')):
    # Keep only graph/cache summaries. Decode at offsets, avoiding repeated
    # copies of the large log and retention of every SDK/test input inventory.
    text, decoder, selected, position = path.read_text(), json.JSONDecoder(), [], 0
    while position < len(text):
        while position < len(text) and text[position].isspace():
            position += 1
        if position == len(text):
            break
        row, position = decoder.raw_decode(text, position)
        if mnemonics is None or row.get('mnemonic') in mnemonics:
            selected.append({key: row.get(key) for key in ['mnemonic', 'targetLabel', 'listedOutputs', 'cacheHit', 'runner', 'status', 'metrics']})
    return selected


def runner_digest(root):
    # The graph runner is configured as an execution tool, outside bazel-bin's
    # target configuration. Require a single payload identity across configs.
    outputs = (root / 'bazel-bin').resolve(strict=True).parent.parent
    digests = {hashlib.sha256(path.read_bytes()).hexdigest()
        for path in outputs.glob('*/bin/graph_runner.runner/GraphBuild.dll')}
    assert len(digests) == 1, 'Missing or conflicting graph runner payloads'
    return digests.pop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--cache-url', required=True)
    parser.add_argument('--phase', choices=['producer', 'consumer'], required=True)
    parser.add_argument('--seed-report', type=Path)
    parser.add_argument('--demo', action='store_true', help='consumer only: time build recovery and actual tests separately; skip forced project recovery')
    parser.add_argument('--body-edit', action='store_true', help='with --demo: rebuild and retest a unique Pipelines body edit, then restore the source and products')
    parser.add_argument('--discard-output-base', action='store_true', help="with --demo: after success, remove only this run's fresh Bazel base; retain reports")
    parser.add_argument('--host-space-path', type=Path, required=True)
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert bool(args.seed_report) == (args.phase == 'consumer')
    assert not args.demo or args.phase == 'consumer'
    assert not args.body_edit or args.demo
    assert not args.discard_output_base or args.demo
    root, results = args.workspace.resolve(), args.results.resolve()
    assert args.output_base.is_absolute() and not args.output_base.exists()
    base = args.output_base.resolve()
    assert not base.is_relative_to(root) and not root.is_relative_to(base)
    assert not results.is_relative_to(root) and not root.is_relative_to(results)
    assert not results.is_relative_to(base) and not base.is_relative_to(results)
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
    marker = root / 'suite-recovery-request.txt'
    assert not marker.exists()
    command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--nosystem_rc', '--nohome_rc', '--noworkspace_rc',
        '--output_base=' + str(base)]
    options = ['--jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1',
        '--local_test_jobs=1', '--disk_cache=', '--remote_cache=' + args.cache_url, '--remote_cache_async=false',
        '--remote_download_outputs=all', '--remote_upload_local_results=' + str(args.phase == 'producer').lower(),
        '--nocache_test_results', '--test_output=errors', '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + args.cache_url]
    if os.environ.get('RULES_MSBUILD_TEST_REPOSITORY_CACHE'):
        options += ['--repository_cache=' + os.environ['RULES_MSBUILD_TEST_REPOSITORY_CACHE']]
    # Native producers create their own Bubblewrap namespace and declare no-sandbox.
    options += ['--lockfile_mode=error', '--spawn_strategy=linux-sandbox', '--strategy=RuntimeNative=local']
    rows = []
    completed = False
    mutation = json.loads(Path(__file__).with_name('runtime_source_host_edit.json').read_text()) if args.body_edit else None
    originals = {mutation['implementation']: (root / mutation['implementation']).read_bytes()} if mutation else {}

    def run(label, whole=False):
        subprocess.run(['fstrim', '/'], check=True, capture_output=True)
        disk = os.statvfs(args.host_space_path)
        required_gib = 4 if args.demo and not whole else 12
        assert disk.f_bavail * disk.f_frsize >= required_gib * 1024**3, 'Insufficient physical host disk headroom'
        events, execution = results / (label + '.bep'), results / (label + '.execution.json')
        start = time.monotonic()
        build_seconds = None
        if args.demo:
            print('Recovering the 481-compilation runtime graph...' if whole else 'Building a unique Pipelines body edit...', flush=True)
            build_log = results / (label + '-build.execution.json')
            with (results / (label + '-build.log')).open('w') as log:
                subprocess.run(command + ['build', *sorted(targets), *options,
                    '--execution_log_json_file=' + str(build_log)], cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
            build_seconds = time.monotonic() - start
            build_actions = graph_actions(build_log, mnemonics=None)
            recovered = [row for row in build_actions if row['mnemonic'] in ['MSBuildGraph', 'MSBuildGraphRestore', 'RuntimeNative']]
            assert recovered
            if whole:
                assert all(row['cacheHit'] and row['runner'] == 'remote cache hit' for row in recovered), recovered
                assert sum(row['mnemonic'] == 'RuntimeNative' for row in recovered) == 5
                assert all(row['cacheHit'] for row in build_actions), 'Demo requires complete remote build recovery'
            else:
                assert not any(row['mnemonic'] == 'MSBuildGraphRestore' and not row['cacheHit'] for row in recovered), recovered
            (results / (label + '-build-actions.json')).write_text(json.dumps(recovered, indent=2) + '\n')
            build_log.unlink()
            assert runner_digest(root) == seed['runnerSha256'], 'Producer/consumer runner bytes differ'
            print(f'Build completed in {build_seconds:.2f}s; executing nine test targets (test cache disabled)...', flush=True)
        test_start = time.monotonic()
        with (results / (label + '.log')).open('w') as log:
            subprocess.run(command + ['test', *sorted(targets), *options, '--build_event_json_file=' + str(events),
                '--execution_log_json_file=' + str(execution)], cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
        command_seconds = time.monotonic() - start
        test_seconds = time.monotonic() - test_start
        verification_start = time.monotonic()
        records = [json.loads(line) for line in events.read_text().splitlines()]
        tests = [event for event in records if 'testResult' in event]
        assert len(tests) == 9 and {event['id']['testResult']['label'] for event in tests} == targets
        assert all(event['testResult']['status'] == 'PASSED' and not event['testResult'].get('cachedLocally') and
            not event['testResult'].get('executionInfo', {}).get('cachedRemotely') for event in tests), tests
        graph = root / 'bazel-bin/graph.graph'
        report = json.loads((graph / 'report.json').read_text())
        runner_sha256 = runner_digest(root)
        actions = recovered if args.demo else graph_actions(execution)
        (results / (label + '-actions.json')).write_text(json.dumps(actions, indent=2) + '\n')
        main = next(row for row in actions if row.get('mnemonic') == 'MSBuildGraph' and any(path.endswith('/graph.graph') for path in row['listedOutputs']))
        if args.phase == 'consumer':
            assert bool(main.get('cacheHit')) == whole, main
            if whole:
                restore = next(row for row in actions if row['mnemonic'] == 'MSBuildGraphRestore' and row['targetLabel'] == '//:graph_restore')
                assert restore['cacheHit'] and restore['runner'] == 'remote cache hit', restore
            if not whole:
                misses = mutation['expectedMisses']['body'] if label == 'body' else 0
                assert (report['hits'], report['misses']) == (481 - misses, misses), report
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
            assert signatures == seed['signatures'], 'Recovered test outcomes differ'
            if label == 'body':
                assert files.keys() == seed['files'].keys()
                assert files[mutation['implDll']] != seed['files'][mutation['implDll']]
                assert files[mutation['refDll']] == seed['files'][mutation['refDll']]
            else:
                assert files == seed['files'], 'Recovered products differ'
        row = dict(case=label, seconds=time.monotonic()-start, commandSeconds=command_seconds,
            buildSeconds=build_seconds, testCommandSeconds=test_seconds, verificationSeconds=time.monotonic()-verification_start,
            buildSpawns=len(build_actions) if args.demo else None,
            executedBuildMnemonics=sorted({row['mnemonic'] for row in build_actions if not row['cacheHit']}) if args.demo else None,
            testDurationsSeconds={event['id']['testResult']['label']: int(event['testResult']['testAttemptDurationMillis']) / 1000 for event in tests},
            machine=socket.gethostname(), workspace=str(root),
            contractSha256=hashlib.sha256((root / 'graph.generated.json').read_bytes()).hexdigest(),
            runnerSha256=runner_sha256,
            restoreExecutions=sum(row['mnemonic'] == 'MSBuildGraphRestore' and not row['cacheHit'] for row in actions),
            evaluationState=None if main.get('cacheHit') else report.get('evaluationState'), executedTests=9, outcomes=dict(outcomes), runtimeObservations=observations, wholeActionHit=bool(main.get('cacheHit')),
            reportOrigin='producer-cache' if main.get('cacheHit') else 'executed',
            hits=None if main.get('cacheHit') else report['hits'], misses=None if main.get('cacheHit') else report['misses'], files=files, signatures=signatures)
        rows.append(row)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        if args.phase == 'producer':
            (results / 'seed.json').write_text(json.dumps(row, indent=2) + '\n')
        execution.unlink()
        if args.demo:
            print(f"PASS: {outcomes['passed']:,} passed / {outcomes['skipped']} skipped; "
                f"build + tests {command_seconds:.2f}s; verification {row['verificationSeconds']:.2f}s", flush=True)
            if not whole:
                print(f"Projects: {report['hits']} reused / {report['misses']} compiled; reference assembly unchanged", flush=True)
        print(json.dumps({k:v for k,v in row.items() if k not in ['files','signatures']}), flush=True)

    try:
        generated.write_text(prefix + '    msbuild_graph(\n' + action)
        marker.write_text('suite-recovery-seed')
        run('seed' if args.phase == 'producer' else 'whole-recovery', whole=args.phase == 'consumer')
        if args.body_edit:
            source = root / mutation['implementation']
            anchor = mutation['bodyAnchor'].encode()
            original_source = originals[mutation['implementation']]
            assert original_source.count(anchor) == 1
            source.write_bytes(original_source.replace(anchor, anchor + b'\n            GC.KeepAlive("runtime-demo-' + uuid.uuid4().hex.encode() + b'");'))
            try:
                run('body')
            finally:
                source.write_bytes(original_source)
            with (results / 'restore-original.log').open('w') as log:
                subprocess.run(command + ['build', *sorted(targets), *options], cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
            workspace = root / 'bazel-bin/graph.graph/workspace'
            for name in ['implDll', 'refDll']:
                path = mutation[name]
                assert hashlib.sha256((workspace / path).read_bytes()).hexdigest() == seed['files'][path]['sha256']
        if args.phase == 'consumer' and not args.demo:
            marker.write_text(uuid.uuid4().hex)
            run('project-recovery')
        completed = True
    finally:
        for path, content in originals.items():
            (root / path).write_bytes(content)
        generated.write_text(original)
        marker.unlink(missing_ok=True)
        subprocess.run(command + ['shutdown'], cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if completed and args.discard_output_base:
            assert not base.is_symlink()
            shutil.rmtree(base)
            subprocess.run(['fstrim', '/'], check=True, capture_output=True)


if __name__ == '__main__':
    main()
