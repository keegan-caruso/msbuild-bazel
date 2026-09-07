"""Run selected unittest suites in a container and retain a structured summary."""
import argparse
import json
import os
import platform
from pathlib import Path
import shutil
import time
import unittest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('suites', nargs='+', choices=['graph', 'graph-execution', 'e2e', 'starlark', 'starlark-native', 'sdk-repository', 'graph-cache', 'graph-handoff', 'bootstrap'])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    summary = {'schemaVersion': 1, 'platform': platform.platform(),
               'machine': platform.machine(), 'bazelMode': os.environ.get('SPIKE_BAZEL_MODE', 'server'),
               'suites': [], 'status': 'running'}
    report = args.output / 'summary.json'

    def save():
        report.write_text(json.dumps(summary, indent=2) + '\n')

    save()
    for name in args.suites:
        print(f'Running {name}; log: {args.output / (name + ".log")}', flush=True)
        started = time.monotonic()
        with (args.output / (name + '.log')).open('w', buffering=1) as log:
            suite = unittest.TestLoader().discover(str(root / 'tests' / name.replace('-', '_')))
            result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
        record = {
            'name': name, 'testsRun': result.testsRun,
            'failures': len(result.failures), 'errors': len(result.errors),
            'skipped': [{'test': test.id(), 'reason': reason} for test, reason in result.skipped],
            'unexpectedSuccesses': len(result.unexpectedSuccesses),
            'seconds': round(time.monotonic() - started, 2),
            'status': 'passed' if result.wasSuccessful() and result.testsRun else 'failed',
        }
        summary['suites'].append(record)
        save()
        print(json.dumps(record), flush=True)

    summary['status'] = 'passed' if all(s['status'] == 'passed' for s in summary['suites']) else 'failed'
    save()
    # Failed tests retain their temporary workspaces. Preserve small diagnostic
    # files, not copied SDKs, binaries, caches, or execroot symlink trees.
    if summary['status'] == 'failed':
        excluded = {'.tools', '.cache', 'bin', 'obj', 'disk-cache', 'bazel-base',
                    'second-bazel-base', 'bazel-user', 'external', 'execroot'}
        for candidate in Path('/tmp').iterdir():
            if not candidate.is_dir() or not candidate.name.startswith(('msbuild-', 'graph-', 'starlark-')):
                continue
            for directory, dirs, files in os.walk(candidate, followlinks=False):
                dirs[:] = [d for d in dirs if d not in excluded and not d.startswith('bazel-')]
                for filename in files:
                    source = Path(directory) / filename
                    if source.is_symlink() or not (filename == 'report.json' or source.suffix == '.log'):
                        continue
                    target = args.output / 'failures' / source.relative_to('/tmp')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, target)
    return 0 if summary['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
