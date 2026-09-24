"""Run pinned upstream bazel-bench against a committed prepared workspace."""
import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shlex
import statistics
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def summarize(csv_path, runs, units):
    log = Path(csv_path).with_name('benchmark.log')
    if log.exists() and 'Bazel command failed with exit code' in log.read_text():
        raise RuntimeError('Benchmark warm-up, sample or cleanup failed; inspect benchmark.log')
    with Path(csv_path).open() as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != runs * units or any(int(r['exit_status']) != 0 for r in rows):
        raise RuntimeError('Missing or failed benchmark samples; inspect raw.csv and benchmark.log')
    groups = {}
    for row in rows:
        seconds = float(row['wall'])
        if not math.isfinite(seconds) or seconds < 0:
            raise RuntimeError('Invalid wall-time sample')
        groups.setdefault(row['bazel_commit'], []).append(seconds)
    if len(groups) != units or any(len(values) != runs for values in groups.values()):
        raise RuntimeError('Unexpected benchmark units or repetition counts')
    return {key: dict(samples=values, medianSeconds=statistics.median(values),
                      minSeconds=min(values), maxSeconds=max(values)) for key, values in groups.items()}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--commit', default='HEAD')
    p.add_argument('--versions', nargs='+', choices=['8.8.0', '9.2.0'], default=['9.2.0'])
    p.add_argument('--mode', choices=['analysis', 'clean', 'noop'], default='analysis')
    p.add_argument('--runs', type=int, default=5)
    workloads = json.loads((ROOT/'benchmarks/workloads.json').read_text())
    p.add_argument('--workload', choices=workloads, default='synthetic')
    p.add_argument('--target', action='append', help='Repeat for selected roots; required for runtime')
    p.add_argument('--output-groups')
    p.add_argument('--jobs', type=int)
    p.add_argument('--workers', type=int)
    a = p.parse_args()
    for key, value in workloads[a.workload].items():
        if getattr(a, key) is None:
            setattr(a, key, value)
    if not a.target:
        p.error('Declare selected runtime roots with --target; whole-runtime support is not implied')
    if isinstance(a.target, str):
        a.target = [a.target]
    if a.runs < 1 or a.jobs < 1 or a.workers < 0 or len(set(a.versions)) != len(a.versions):
        p.error('Use positive runs/jobs, nonnegative workers and unique versions')
    source, output = a.source.resolve(), a.output.resolve()
    if output.is_relative_to(source) or output.is_relative_to(ROOT):
        p.error('Output must be outside source and rules checkout')
    if subprocess.check_output(['git', '-C', str(source), 'rev-parse', '--show-toplevel'], text=True).strip() != str(source):
        p.error('--source must be a standalone prepared repository root')
    if subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'], text=True).strip():
        p.error('Commit prepared inputs first, or use benchmarks/snapshot.py')
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', a.commit+'^{commit}'], text=True).strip()
    pins = json.loads((ROOT/'benchmarks/tool.json').read_text())
    tool = ROOT/'.tools/bazel-bench'
    revision = subprocess.check_output(['git', '-C', str(tool/'source'), 'rev-parse', 'HEAD'], text=True).strip()
    if revision != pins['commit'] or subprocess.check_output(['git', '-C', str(tool/'source'), 'status', '--porcelain'], text=True).strip():
        raise RuntimeError('Run scripts/setup-bench.sh; benchmark source pin differs')
    output.mkdir(parents=True, exist_ok=False)
    units = []
    for version in a.versions:
        launcher = output/('bazel-'+version)
        launcher.write_text('#!/usr/bin/env bash\nexport USE_BAZEL_VERSION='+shlex.quote(version)+'\nexec '+shlex.quote(str(ROOT/'scripts/bazel-launcher.sh'))+' "$@"\n')
        launcher.chmod(0o755)
        actual = subprocess.check_output([str(launcher), '--version'], text=True).strip()
        if actual != 'bazel '+version:
            raise RuntimeError('Bazel version differs: '+actual)
        flags = ['--jobs='+str(a.jobs), '--disk_cache=', '--remote_cache=', '--lockfile_mode=off']
        if a.output_groups:
            flags.append('--output_groups='+a.output_groups)
        if a.mode == 'analysis':
            flags.append('--nobuild')
        if a.workers:
            flags += ['--strategy=MSBuildAssembly=worker', '--worker_max_instances=MSBuildAssembly='+str(a.workers)]
        command = ['--output_base='+str(output/('base-'+version)), '--ignore_all_rc_files', 'build', *flags, *a.target]
        units.append(dict(bazel_binary=str(launcher), command=shlex.join(command)))
    config = dict(global_options=dict(project_source=str(source), project_commit=commit,
        bazel_source=str(source), runs=a.runs, collect_profile=True), units=units)
    (output/'config.json').write_text(json.dumps(config, indent=2)+'\n')
    metadata = dict(benchmarkTool=pins, projectCommit=commit, harnessCommit=subprocess.check_output(
        ['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
        harnessDirty=bool(subprocess.check_output(['git', '-C', str(ROOT), 'status', '--porcelain'], text=True).strip()),
        sdk=os.environ.get('RULES_MSBUILD_DOTNET_ROOT'),
        fixtureModule=subprocess.check_output(['git', '-C', str(source), 'show', commit+':MODULE.bazel'], text=True), platform=platform.platform(), machine=platform.machine(),
        cpuCount=os.cpu_count(),
        cgroupMemoryLimit=Path('/sys/fs/cgroup/memory.max').read_text().strip() if Path('/sys/fs/cgroup/memory.max').exists() else None,
        sdkVersion=subprocess.check_output([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'), '--version'], cwd=ROOT, text=True).strip(),
        harnessRunnerSha256=hashlib.sha256((ROOT/'tools/ExplicitBuild/bin/Release/net10.0/ExplicitBuild.dll').read_bytes()).hexdigest(),
        mode=a.mode, jobs=a.jobs, workers=a.workers,
        timingScope='server-startup-excluded', memoryScope='Bazel JVM heap after GC; not process-tree peak',
        cacheState='warm acquisition and filesystem; external disk/remote action caches disabled',
        warmup='one full unmeasured command per unit; clean/shutdown afterward except noop')
    (output/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
    command = [str(tool/'venv/bin/python'), str(tool/'source/benchmark.py'),
        '--benchmark_config='+str(output/'config.json'), '--data_directory='+str(output),
        '--csv_file_name=raw.csv', '--project_label=rules_msbuild', '--prefetch_ext_deps',
        '--clean='+str(a.mode != 'noop').lower(), '--shutdown='+str(a.mode != 'noop').lower()]
    try:
        with (output/'benchmark.log').open('w') as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True)
        summary = summarize(output/'raw.csv', a.runs, len(units))
        (output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
        print(json.dumps(summary, indent=2))
    finally:
        for unit in units:
            base = shlex.split(unit['command'])[0]
            subprocess.run([unit['bazel_binary'], base, '--ignore_all_rc_files', 'shutdown'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
