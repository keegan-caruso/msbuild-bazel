"""Run the existing hello sources using a synchronized library/application graph."""
import os
from pathlib import Path
import subprocess
import sys

rules = Path(__file__).resolve().parents[2]
workspace = Path(sys.argv[1]).resolve()
subprocess.run([sys.executable, str(rules/'examples/hello/create.py'), str(workspace), '--sync'], check=True)
bazel = os.environ.get('RULES_MSBUILD_BAZEL', str(rules/'scripts/bazel-launcher.sh'))
startup = [bazel, '--output_base=' + str(workspace.parent/(workspace.name+'-base'))]
try:
    for args in [['run', '//:App_App'], ['test', '//:Tests'], ['run', '//:sync', '--', '--check']]:
        subprocess.run(startup + args, cwd=workspace, check=True)
finally:
    subprocess.run(startup + ['shutdown'], cwd=workspace, check=True)
