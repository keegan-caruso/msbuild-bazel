"""Single entry point for stateful workload adapters and their parity controls."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = {
    'runtime': 'upstream/runtime_benchmark.py',
    'avalonia': 'upstream/avalonia_worker.py',
    'synthetic': 'benchmark.py',
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('workload', choices=ADAPTERS)
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    a = p.parse_args()
    return subprocess.run([sys.executable, str(ROOT/'tests/graph_build'/ADAPTERS[a.workload]), *a.arguments], env=os.environ).returncode


if __name__ == '__main__':
    raise SystemExit(main())
