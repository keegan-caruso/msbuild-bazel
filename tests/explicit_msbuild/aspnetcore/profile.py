"""Profile one large-graph invocation without the expensive JSON execution log.

Use a fresh output base for cold/cache recovery comparisons. Pass additional Bazel
flags after -- (for example --remote_accept_cached=false for a cold producer).
Trace task totals overlap; they are aggregate task time, not additive wall time.
"""
import argparse
import collections
import gzip
import json
import os
from pathlib import Path
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('workspace', type=Path)
parser.add_argument('base', type=Path)
parser.add_argument('report', type=Path)
parser.add_argument('--cache', default='')
parser.add_argument('--cache-only', action='store_true')
parser.add_argument('--jobs', type=int, default=2)
args, extra = parser.parse_known_args()
report = args.report.resolve()
report.parent.mkdir(parents=True, exist_ok=True)
startup = [os.environ['RULES_MSBUILD_BAZEL'], '--host_jvm_args=-Xmx1024m', '--output_base='+str(args.base.resolve()), '--ignore_all_rc_files']
command = startup + ['build', '//upstream:benchmark', '--strategy=MSBuildAssembly=worker', '--worker_max_instances=MSBuildAssembly=2', '--jobs='+str(args.jobs), '--local_resources=cpu=2', '--disk_cache=', '--remote_cache='+args.cache, '--remote_download_outputs=all', '--profile='+str(report.with_suffix('.trace.json.gz')), '--noslim_profile', '--experimental_profile_additional_tasks=action_fs_staging', '--experimental_profile_additional_tasks=vfs_md5', '--experimental_profile_include_target_label', '--build_event_json_file='+str(report.with_suffix('.bep'))]
if args.cache_only:
    assert args.cache, '--cache-only requires an HTTP cache'
    command += ['--remote_upload_local_results=false']
command += extra[1:] if extra[:1] == ['--'] else extra
try:
    start = time.perf_counter()
    with report.with_suffix('.log').open('w') as log:
        result = subprocess.run(command, cwd=args.workspace, stdout=log, stderr=subprocess.STDOUT)
    wall = time.perf_counter()-start
    assert result.returncode == 0, report.with_suffix('.log')
    metrics = next(json.loads(line)['buildMetrics'] for line in report.with_suffix('.bep').read_text().splitlines() if 'buildMetrics' in json.loads(line))
    runners = {row['name']: row['count'] for row in metrics['actionSummary']['runnerCount']}
    if args.cache_only:
        assert runners.get('remote cache hit') == 578 and not runners.get('worker') and not runners.get('linux-sandbox'), runners
    with gzip.open(report.with_suffix('.trace.json.gz')) as source:
        events = json.load(source)['traceEvents']
    categories = collections.Counter()
    named = collections.Counter()
    for event in events:
        seconds = event.get('dur', 0)/1e6
        categories[event.get('cat', '')] += seconds
        if event.get('cat') == 'general information':
            named[event['name']] += seconds
    summary = dict(seconds=wall, command=command, runners=runners, timing=metrics['timingMetrics'], artifacts=metrics['artifactMetrics'], network=metrics.get('networkMetrics'), aggregateTaskSeconds=dict(categories), aggregateOperations=dict(named.most_common(20)))
    report.write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps({'seconds': wall, 'runners': runners}), flush=True)
finally:
    subprocess.run(startup+['shutdown'], cwd=args.workspace, check=True)
