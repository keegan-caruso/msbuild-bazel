#!/usr/bin/env bash
# Optional benchmark dependencies; never part of normal setup or timed builds.
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/env.sh"
cd "$REPO_ROOT"
"${BENCHMARK_PYTHON:-python3}" - <<'PY'
import json
from pathlib import Path
import subprocess
import sys
if not (3, 9) <= sys.version_info[:2] <= (3, 12):
    raise SystemExit('Pinned benchmark dependencies require Python 3.9-3.12; set BENCHMARK_PYTHON')
pins = json.loads(Path('benchmarks/tool.json').read_text())
root = Path('.tools/bazel-bench')
source = root/'source'
if not source.exists():
    source.mkdir(parents=True)
    subprocess.run(['git', 'init', str(source)], check=True)
    subprocess.run(['git', '-C', str(source), 'remote', 'add', 'origin', pins['repository']], check=True)
if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
    raise SystemExit('Benchmark checkout has local changes; use a clean tool directory')
subprocess.run(['git', '-C', str(source), 'fetch', '--depth=1', 'origin', pins['commit']], check=True)
subprocess.run(['git', '-C', str(source), 'checkout', '--detach', pins['commit']], check=True)
venv = root/'venv'
subprocess.run([sys.executable, '-m', 'venv', str(venv)], check=True)
subprocess.run([str(venv/'bin/python'), '-m', 'pip', 'install', '--disable-pip-version-check', '-r', 'benchmarks/requirements.txt'], check=True)
subprocess.run([str(venv/'bin/python'), '-m', 'pip', 'check'], check=True)
PY
