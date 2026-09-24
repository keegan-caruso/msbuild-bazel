"""Measure configured managed roots using BEP counts instead of an execution log.

A cold run requires a fresh output base. Warm runs reuse that base. SDK/package
acquisition and declaration preparation must precede timing. Keep raw restore
separate. Detailed MSBuild evaluation profiling is a separate experiment.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path
import subprocess
import time

from timing_tools import verify_tools

p = argparse.ArgumentParser(description=__doc__)
for name in ['workspace', 'selection', 'base', 'report']:
    p.add_argument(name, type=Path)
p.add_argument('--case', choices=['cold', 'warm', 'seed', 'recovery'], required=True)
p.add_argument('--cache', default='')
a = p.parse_args()
w, base, out = a.workspace.resolve(), a.base.resolve(), a.report.resolve()
assert not out.exists(), 'Report must be new'
if a.case in ['cold', 'recovery']:
    assert not base.exists(), 'Cold/recovery requires a fresh output base'
if a.case in ['seed', 'recovery']:
    assert a.cache, 'Seed/recovery requires an HTTP cache'
out.mkdir(parents=True)
tools = verify_tools('9.2.0', cwd=out)
entries = json.loads(a.selection.read_text())['entries']
targets = ['//upstream:' + e['project'].removesuffix('.csproj').replace('/', '_') + '_' + e['framework'] for e in entries]
command = [tools['bazelExecutable'], '--host_jvm_args=-Xmx1536m', '--output_base='+str(base), '--ignore_all_rc_files', 'build', *targets,
           '--jobs=2', '--strategy=MSBuildAssembly=worker', '--worker_max_instances=MSBuildAssembly=2', '--output_groups=reference',
           '--disk_cache=', '--remote_cache='+a.cache, '--remote_download_outputs=all',
           '--remote_upload_local_results='+str(a.case == 'seed').lower(),
           '--build_event_json_file='+str(out/'build.bep'), '--profile='+str(out/'trace.json.gz')]
if a.case in ['cold', 'seed']:
    command += ['--remote_accept_cached=false']
start = time.monotonic()
with (out/'build.log').open('w') as log:
    result = subprocess.run(command, cwd=w, stdout=log, stderr=subprocess.STDOUT, timeout=2400)
wall = time.monotonic() - start
report = dict(case=a.case, wallSeconds=round(wall, 3), exitCode=result.returncode, toolchain=tools, roots=entries, command=command)
(out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
result.check_returncode()
events = [json.loads(line) for line in (out/'build.bep').read_text().splitlines()]
metrics = next(e['buildMetrics'] for e in events if 'buildMetrics' in e)
runners = {r['name']: int(r['count']) for r in metrics['actionSummary'].get('runnerCount', [])}
report.update(runners=runners, metrics=metrics)
if a.case == 'cold':
    assert runners.get('worker', 0) > 0 and not runners.get('remote cache hit'), runners
if a.case == 'recovery':
    assert runners.get('remote cache hit', 0) > 0 and not runners.get('worker') and not runners.get('linux-sandbox'), runners
# Diagnostics describe action costs, not serial wall-clock segments. On warm or
# recovered runs these files may describe prior execution; do not sum them as new work.
phases = collections.Counter()
profiles = list((base/'execroot/_main/bazel-out').glob('*/bin/upstream/*.diagnostics/worker.json'))
for path in profiles:
    row = json.loads(path.read_text())
    for key in ['identitySeconds', 'snapshotSeconds', 'preparationSeconds', 'childSeconds', 'publicationSeconds']:
        phases[key] += row.get(key, 0)
report['recordedWorkerProfiles'] = len(profiles)
report['recordedWorkerPhaseSeconds'] = dict(phases)
hashes = {}
for path in sorted((w/'bazel-bin/upstream').glob('*.reference/*')):
    if path.is_file():
        hashes[str(path.relative_to(w/'bazel-bin'))] = hashlib.sha256(path.read_bytes()).hexdigest()
assert hashes
(out/'reference-hashes.json').write_text(json.dumps(hashes, indent=2)+'\n')
(out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(dict(wallSeconds=report['wallSeconds'], runners=runners, recordedWorkerPhaseSeconds=dict(phases))), flush=True)
