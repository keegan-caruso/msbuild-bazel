"""Single entry point for stateful workload adapters and their parity controls."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = {
    'orchard': 'orchard_compatibility/benchmark.py',
    'avalonia': 'avalonia/benchmark.py',
    'aspnetcore': 'aspnetcore/benchmark.py',
    'oss': 'oss/benchmark.py',
    'compiler': 'compiler_reuse.py',
    'runtime-managed': 'runtime/managed_timing.py',
    'runtime': 'runtime/scenario_timing.py',
    'runtime-leaf': 'runtime/leaf_timing.py',
    'runtime-raw-leaf': 'runtime/raw_leaf_timing.py',
    'runtime-raw-cold': 'runtime/raw_cold_timing.py',
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('workload', choices=ADAPTERS)
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    a = p.parse_args()
    env = dict(os.environ)
    # Existing preparation adapters share modules in tests/explicit_msbuild.
    env['PYTHONPATH'] = os.pathsep.join([str(ROOT), str(ROOT/'tests/explicit_msbuild'), env.get('PYTHONPATH', '')])
    return subprocess.run([sys.executable, str(ROOT/'tests/explicit_msbuild'/ADAPTERS[a.workload]), *a.arguments], env=env).returncode


if __name__ == '__main__':
    raise SystemExit(main())
