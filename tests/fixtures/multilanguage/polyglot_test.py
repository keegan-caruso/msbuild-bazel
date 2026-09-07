"""Run already-built language programs using declared Bazel runfiles only."""
import argparse
import os
from pathlib import Path
import subprocess
from python.runfiles import runfiles

parser = argparse.ArgumentParser()
for name in ('python', 'typescript', 'dotnet'):
    parser.add_argument('--' + name, required=True)
parser.add_argument('--bundles', nargs='+', required=True)
args = parser.parse_args()
r = runfiles.Create()
def locate(path):
    logical = path[3:] if path.startswith('../') else '_main/' + path.removeprefix('./')
    resolved = r.Rlocation(logical)
    if not resolved or not Path(resolved).exists():
        raise RuntimeError('missing runfile: ' + logical)
    return resolved

def run(command):
    result = subprocess.run(command, env=dict(os.environ, **r.EnvVars()), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()

bundle = next(locate(p) for p in args.bundles if p.endswith('.bundle'))
actual = [run([locate(args.python)]), run([locate(args.typescript)]),
          run([locate(args.dotnet), str(Path(bundle) / 'artifacts/src/App/bin/Release/net10.0/App.dll')])]
expected = ['python-v1', 'typescript-v1', 'shared-v1:left|shared-v1:right']
assert actual == expected, (actual, expected)
print('|'.join(actual))
