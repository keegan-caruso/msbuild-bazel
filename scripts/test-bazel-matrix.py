#!/usr/bin/env python3
"""Run the same supported-version gates with bootstrap or optional Nix tools."""
import argparse
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--versions', nargs='+', choices=['8.8.0', '9.2.0'], default=['8.8.0', '9.2.0'])
    args = parser.parse_args()
    output = args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error('--output must be outside the checkout to prevent inherited MSBuild inputs')
    output.mkdir(parents=True, exist_ok=False)
    # Apply precisely the same environment contract as the shell wrappers.
    env = json.loads(subprocess.check_output(['bash', '-c',
        'source scripts/env.sh; python3 -c "import json, os; print(json.dumps(dict(os.environ)))"'], cwd=ROOT, text=True))
    results = {}

    def run(name, command, selected):
        start = time.monotonic()
        with (output/(name+'.log')).open('w') as log:
            result = subprocess.run(command, cwd=ROOT, env=selected, stdout=log, stderr=subprocess.STDOUT)
        results[name] = dict(command=command, exitCode=result.returncode, seconds=time.monotonic()-start)
        (output/'results.json').write_text(json.dumps(results, indent=2)+'\n')
        print(name, result.returncode, flush=True)
        return result.returncode == 0

    for name, command in [
        ('setup-starlark', ['bash', 'scripts/tooling.sh', 'setup-starlark']),
        ('runner', ['bash', 'scripts/check-dotnet.sh']),
        ('bootstrap', ['python3', '-m', 'unittest', 'discover', '-s', 'tests/bootstrap', '-v']),
    ]:
        if not run(name, command, env):
            return 1
    for version in args.versions:
        selected = dict(env, USE_BAZEL_VERSION=version, RULES_MSBUILD_BAZEL_VERSION=version)
        for name, command in [
            ('check', ['bash', 'scripts/check.sh']),
            ('analysis', ['bash', 'scripts/check-analysis.sh']),
            ('sdk-repository', ['python3', '-m', 'unittest', 'discover', '-s', 'tests/sdk_repository', '-v']),
            ('acceptance', ['python3', 'tests/explicit_msbuild/acceptance.py', str(output/version)]),
        ]:
            if not run(version+'-'+name, command, selected):
                break
        run(version+'-shutdown', ['bash', 'scripts/bazel.sh', 'shutdown'], selected)
    return int(any(row['exitCode'] for row in results.values()))


if __name__ == '__main__':
    raise SystemExit(main())
