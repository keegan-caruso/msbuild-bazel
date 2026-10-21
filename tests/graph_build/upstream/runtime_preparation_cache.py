"""Measure and verify declared preparation on an owned runtime source workspace.

Use a prepared source workspace (native locks and mappings present), not the
pruned build consumer. Consumer mode requires identical sources and declarations,
a fresh output base, and a stopped producer. Reports remain outside Git.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time

from runtime_sync_inputs import SYNC_SRCS, action_records

ROOT = Path(__file__).resolve().parents[3]
OUTPUTS = ['graph.generated.json', 'graph.generated.bzl']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--cache-url', required=True)
    parser.add_argument('--consumer', action='store_true')
    parser.add_argument('--seed-report', type=Path, help='producer seed.json, required for independent consumer mode')
    parser.add_argument('--controls', action='store_true', help='requalify body/API, props, mappings and lock-byte edits')
    parser.add_argument('--producer-controls', type=Path, help='JIT fixture source_runtime producer; qualify an actual reference-assembly API change')
    parser.add_argument('--reference-contracts', type=Path, help='compare retained ordinary-sync declarations instead of executing ordinary sync again')
    parser.add_argument('--profile', action='store_true', help='separate diagnostic run; phase totals overlap and are not benchmark scores')
    parser.add_argument('--resume', action='store_true', help='reuse a seeded output base; requires retained reference contracts and skips cold timing')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert not (args.consumer and (args.controls or args.producer_controls or args.reference_contracts or args.resume))
    assert not (args.controls and args.producer_controls)
    assert args.consumer == bool(args.seed_report), 'Use --seed-report exactly with --consumer'
    root, results, base = args.workspace.resolve(), args.results.resolve(), args.output_base.resolve()
    results.mkdir(parents=True, exist_ok=False)
    assert base.exists() == args.resume, 'Use a fresh output base, or --resume for a seeded producer'
    assert not args.resume or args.reference_contracts, 'Resuming requires retained ordinary-sync declarations'
    build = root / 'BUILD.bazel'
    original_build = build.read_text()
    declaration = next(line for line in original_build.splitlines() if line.startswith('msbuild_sync(name="sync",'))
    assert SYNC_SRCS in declaration, 'Use the declared-source preparation driver'
    baseline = declaration.replace('name="sync"', 'name="preparation_baseline"', 1).replace(',' + SYNC_SRCS, '')
    rows = []

    def outputs():
        return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in OUTPUTS}

    def run(label, target='sync', check=False, expected=0, remote=False):
        trace = results / (label + '.actions.json')
        command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(base), 'run', '//:' + target,
            '--remote_cache=' + args.cache_url, '--disk_cache=', '--remote_cache_async=false',
            '--execution_log_json_file=' + str(trace), '--noshow_progress', '--jobs=1',
            '--strategy=MSBuildGraph=worker', '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1',
            '--strategy=RuntimeNative=standalone', '--remote_download_outputs=all',
            '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + args.cache_url]
        if args.consumer:
            command.append('--lockfile_mode=error')
        if args.profile:
            command.append('--action_env=RULES_MSBUILD_SYNC_PROFILE=1')
            command.append('--profile=' + str(results / (label + '.profile.json.gz')))
        if check:
            command += ['--', '--check']
        start = time.monotonic()
        with (results / (label + '.log')).open('w') as log:
            environment = dict(os.environ)
            if args.profile:
                environment['RULES_MSBUILD_SYNC_PROFILE'] = '1'
            subprocess.run(command, cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        elapsed = time.monotonic() - start
        spawns = list(action_records(trace))
        selected = [row for row in spawns if row.get('mnemonic') in ['MSBuildSyncPrepare', 'MSBuildSyncBootstrap']]
        preparation = [row for row in selected if row['mnemonic'] == 'MSBuildSyncPrepare']
        assert len(preparation) == expected, selected
        if remote:
            assert all(row.get('cacheHit') and row.get('runner') == 'remote cache hit' for row in selected), selected
            if args.consumer:
                assert all(row.get('cacheHit') and row.get('runner') == 'remote cache hit' for row in spawns), spawns
        elif expected:
            assert all(not row.get('cacheHit') for row in preparation), preparation
        phases = [] if remote else [json.loads(line.split('PROJECT_SYNC_PROFILE ', 1)[1])
            for line in (results / (label + '.log')).read_text().splitlines() if line.startswith('PROJECT_SYNC_PROFILE ')]
        row = dict(case=label, seconds=elapsed, profiled=args.profile, phases=phases, outputs=outputs(), actions=[dict(mnemonic=item['mnemonic'],
            cacheHit=item.get('cacheHit', False), runner=item.get('runner')) for item in spawns])
        rows.append(row)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps({key: value for key, value in row.items() if key != 'actions'}), flush=True)
        # Reclaim deleted private-build blocks outside the measured command.
        subprocess.run(['fstrim', '/'], capture_output=True, check=True)
        return row['outputs']

    originals = {}
    try:
        if args.consumer:
            seed = json.loads(args.seed_report.read_text())
            assert seed['machine'] != socket.gethostname() and seed['workspace'] != str(root), 'Use an independent relocated consumer'
            assert seed['profiled'] == args.profile, 'Use the same diagnostic environment as the producer'
            expected = outputs()
            assert expected == seed['outputs'], 'Consumer declarations differ from the producer'
            assert run('independent-recovery', check=True, expected=1, remote=True) == expected
            assert run('recovered-warm', check=True) == expected
            return
        build.write_text(original_build + '\n' + baseline + '\n')
        if args.reference_contracts:
            expected = {name: hashlib.sha256((args.reference_contracts / name).read_bytes()).hexdigest() for name in OUTPUTS}
        else:
            expected = run('ordinary', target='preparation_baseline')
        if args.resume:
            assert run('declared-resumed', check=True) == expected
        else:
            assert run('declared-cold', expected=1) == expected, 'Declared snapshot differs from ordinary sync'
        for sample in range(3):
            assert run('warm-' + str(sample), check=True) == expected
        if args.controls:
            edit = json.loads(Path(__file__).with_name('runtime_loaded_common_edit.json').read_text())
            paths = [root / edit[key] for key in ['implementation', 'reference']]
            paths += [root / name for name in ['Directory.Build.props', 'mappings.json', 'nuget.lock.json']]
            originals = {path: path.read_bytes() for path in paths}
            body, reference, props, mappings, packages = paths
            anchor = edit['bodyAnchor'].encode()
            assert originals[body].count(anchor) == 1
            body.write_bytes(originals[body].replace(anchor, anchor + b'\n            GC.KeepAlive("preparation-cache-body");'))
            run('body', expected=1)
            run('body-warm', check=True)
            for path, anchor in [(body, edit['implementationAnchor']), (reference, edit['referenceAnchor'])]:
                current = path.read_bytes()
                assert current.count(anchor.encode()) == 1
                path.write_bytes(current.replace(anchor.encode(), anchor.encode() + b'\n        public static int PreparationCacheProbe() => 1;'))
            run('api', expected=1)
            run('api-warm', check=True)
            for label, path in [('props', props), ('mapping', mappings), ('package-lock', packages)]:
                path.write_bytes(originals[path] + b'\n')
                run(label, expected=1)
                run(label + '-warm', check=True)
            for path, data in originals.items():
                path.write_bytes(data)
            assert run('restored', expected=1, remote=True) == expected
            assert run('ordinary-restored', target='preparation_baseline', check=True) == expected
        if args.producer_controls:
            edit = json.loads(Path(__file__).with_name('runtime_loaded_common_edit.json').read_text())
            producer = args.producer_controls.resolve()
            paths = [producer / edit[key] for key in ['implementation', 'reference']]
            originals = {path: path.read_bytes() for path in paths}
            bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(base)]
            execution = Path(subprocess.check_output(bazel + ['info', 'execution_root'], cwd=root, text=True).strip())
            tree, = subprocess.check_output(bazel + ['cquery', '//:refs', '--output=files'], cwd=root, text=True).splitlines()
            reference_dll = execution / tree / 'System.IO.Pipelines.dll'
            before = hashlib.sha256(reference_dll.read_bytes()).hexdigest()
            for path, anchor in zip(paths, [edit['implementationAnchor'], edit['referenceAnchor']]):
                assert originals[path].count(anchor.encode()) == 1
                path.write_bytes(originals[path].replace(anchor.encode(), anchor.encode() + b'\n        public static int PreparationProducerProbe() => 1;'))
            run('producer-api', expected=1)
            assert hashlib.sha256(reference_dll.read_bytes()).hexdigest() != before, 'Producer control did not change reference bytes'
            run('producer-api-warm', check=True)
            for path, data in originals.items():
                path.write_bytes(data)
            assert run('producer-restored', expected=1, remote=True) == expected
            assert hashlib.sha256(reference_dll.read_bytes()).hexdigest() == before
        (results / 'seed.json').write_text(json.dumps(dict(machine=socket.gethostname(), workspace=str(root),
            profiled=args.profile, outputs=expected), indent=2) + '\n')
    finally:
        for path, data in originals.items():
            path.write_bytes(data)
        build.write_text(original_build)
        subprocess.run([str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(base), 'shutdown'],
            cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
