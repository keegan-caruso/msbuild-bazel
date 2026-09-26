"""Measure already-bootstrapped sync checks without changing generated output."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('workspace', type=Path)
p.add_argument('base', type=Path)
p.add_argument('report', type=Path)
p.add_argument('--repetitions', type=int, default=3)
a = p.parse_args()
w, base, report = [v.resolve() for v in [a.workspace, a.base, a.report]]
report.parent.mkdir(parents=True, exist_ok=True)
cmd = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base=' + str(base), '--host_jvm_args=-Xmx1536m', '--ignore_all_rc_files']
original = (w / 'projects.generated.bzl').read_bytes()
rows = []
try:
    for i in range(a.repetitions + 1):
        name = 'warmup' if i == 0 else str(i)
        start = time.monotonic()
        with report.with_suffix('.' + name + '.log').open('w') as log:
            result = subprocess.run(cmd + ['run', '//:sync', '--jobs=2', '--', '--check'], cwd=w, stdout=log, stderr=subprocess.STDOUT)
        row = dict(case=name, seconds=round(time.monotonic() - start, 3), exitCode=result.returncode)
        assert result.returncode == 0, row
        assert (w / 'projects.generated.bzl').read_bytes() == original
        rows.append(row)
        report.write_text(json.dumps(dict(records=rows, generatedSha256=hashlib.sha256(original).hexdigest(), generatedUnchanged=True), indent=2) + '\n')
        print(row, flush=True)
finally:
    subprocess.run(cmd + ['shutdown'], cwd=w, check=True)
