#!/usr/bin/env python3
"""Record independent Bazel version gates; failures do not stop the matrix."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
PINS = json.loads((ROOT / 'nix/bazel-versions.json').read_text())


def run(command, log, timeout, env=None):
    started = time.monotonic()
    with log.open('w') as output:
        process = subprocess.Popen(command, cwd=ROOT, stdout=output, env=env,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
            code = 124
    return dict(command=command, exitCode=code,
                seconds=round(time.monotonic() - started, 2), log=str(log))


def snapshot(destination):
    """Copy owned files once, including pending changes but excluding build state."""
    names = subprocess.check_output(
        ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT
    ).decode().split('\0')
    hashes = {}
    for name in sorted(set(names) - {''}):
        source = ROOT / name
        if not source.is_file():
            continue
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        hashes[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inside', choices=PINS)
    args = parser.parse_args()
    output = args.output.resolve()
    if not args.inside and output.is_relative_to(ROOT):
        parser.error('--output must be outside the checkout to prevent inherited MSBuild inputs')
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    if args.inside:
        scratch = output / 'tmp'
        scratch.mkdir()
        env = dict(os.environ, TMPDIR=str(scratch))
        metadata = dict(platform=platform.platform(), expectedBazelVersion=args.inside,
                        bazelExecutable=os.environ.get('RULES_MSBUILD_BAZEL'),
                        dotnetRoot=os.environ.get('RULES_MSBUILD_DOTNET_ROOT'),
                        sourceRoot=str(ROOT),
                        initialModuleLockSha256=hashlib.sha256((ROOT / 'MODULE.bazel.lock').read_bytes()).hexdigest())
        (output / 'environment.json').write_text(json.dumps(metadata, indent=2) + '\n')
        stages = {
            'setup-starlark': ['bash', 'scripts/tooling.sh', 'setup-starlark'],
            'check': ['bash', 'scripts/check.sh'],
            'query': ['bash', 'scripts/bazel.sh', 'query', '//:repo_setup', '--noshow_progress'],
            'output-base': ['bash', 'scripts/bazel.sh', 'info', 'output_base'],
            'bootstrap': ['python3', '-m', 'unittest', 'discover', '-s', 'tests/bootstrap', '-v'],
            'starlark': ['python3', '-m', 'unittest', 'discover', '-s', 'tests/starlark', '-v'],
            'sdk-repository': ['python3', '-m', 'unittest', 'discover', '-s', 'tests/sdk_repository', '-v'],
            'boundary': ['python3', 'tools/probe_bazel.py', '--output', str(output / 'boundary')],
        }
        try:
            for name, command in stages.items():
                results[name] = run(command, output / (name + '.log'), 900, env)
                print(args.inside, name, results[name]['exitCode'], flush=True)
                (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
        finally:
            results['shutdown'] = run(['bash', 'scripts/bazel.sh', 'shutdown'], output / 'shutdown.log', 60, env)
            (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    else:
        source = output / 'source-snapshot'
        hashes = snapshot(source)
        (output / 'source-hashes.json').write_text(json.dumps(hashes, indent=2) + '\n')
        for version in PINS:
            # Identical initial files and lockfiles; no .git, .tools or build outputs.
            workspace = output / version / 'workspace'
            shutil.copytree(source, workspace)
            command = ['nix', '--extra-experimental-features', 'nix-command flakes',
                       'develop', '.#bazel-' + version.replace('.', '_'),
                       '--no-update-lock-file', '-c', 'python3',
                       str(workspace / 'scripts/test-nix-bazel-matrix.py'), '--inside', version,
                       '--output', str(output / version / 'evidence')]
            results[version] = run(command, output / (version + '.log'), 5400)
            print(version, results[version]['exitCode'], flush=True)
            (output / 'results.json').write_text(json.dumps(results, indent=2) + '\n')
    return int(any(value['exitCode'] for value in results.values()))


if __name__ == '__main__':
    sys.exit(main())
