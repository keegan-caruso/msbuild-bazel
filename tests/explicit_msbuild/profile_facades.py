"""Compare analysis of explicit and facade graphs; no .NET actions execute."""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output', type=Path)
p.add_argument('--projects', type=int, default=200)
p.add_argument('--repetitions', type=int, default=3)
a = p.parse_args()
assert a.projects > 0 and a.repetitions > 0
out = a.output.resolve()
out.mkdir(parents=True)
w = out / 'source'
w.mkdir()
root = Path(__file__).resolve().parents[2]
(w / 'MODULE.bazel').write_text('module(name="facade_profile")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path=' + json.dumps(str(root)) + ')\nregister_toolchains("//:registered")\n')
lines = ['''load("@rules_msbuild//msbuild:defs.bzl", "msbuild_library", "msbuild_project")
load("@rules_msbuild//msbuild:toolchain.bzl", "msbuild_toolchain")
msbuild_toolchain(name="fake",dotnet="dotnet",sdk=":sdk",runner="Runner.dll",runtime_manifest="runtime.json")
filegroup(name="sdk",srcs=["sdk.txt"])
toolchain(name="registered",toolchain=":fake",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
''']
for filename in ['dotnet', 'sdk.txt', 'Runner.dll', 'runtime.json', 'Source.cs']:
    (w / filename).write_text('analysis only\n')
for i in range(a.projects):
    project = f'P{i}.csproj'
    (w / project).write_text('<Project />')
    children = [j for j in [2*i+1, 2*i+2] if j < a.projects]
    lines.append('msbuild_project(name="p%d",project="%s",srcs=["Source.cs"],target_frameworks=["netstandard2.1","net10.0"],deps=%s)' % (i, project, json.dumps([':p'+str(j) for j in children])))
    # Declare both variants in both graphs, but the explicit root analyzes only
    # the net10.0 edges it needs. Loading work is shared between measurements.
    for framework, suffix in [('netstandard2.1', 'standard'), ('net10.0', 'modern')]:
        lines.append('msbuild_library(name="e%d_%s",project="%s",srcs=["Source.cs"],target_framework="%s",deps=%s)' % (i, suffix, project, framework, json.dumps([':e'+str(j)+'_'+suffix for j in children])))
for mode, dep in [('facade', ':p0'), ('explicit', ':e0_modern')]:
    lines.append('msbuild_library(name="%s",project="Root.csproj",target_framework="net10.0",deps=["%s"])' % (mode, dep))
(w / 'Root.csproj').write_text('<Project />')
(w / 'BUILD.bazel').write_text('\n'.join(lines))
bazel = os.environ['RULES_MSBUILD_BAZEL']
version = subprocess.check_output([bazel, '--version'], text=True).strip()
# Warm repository acquisition before timing fresh analysis servers.
with (out / 'warmup.log').open('w') as log:
    subprocess.run([bazel, '--batch', '--output_base='+str(out/'warmup'), '--ignore_all_rc_files', 'build', '//:explicit', '--nobuild', '--lockfile_mode=off', '--repository_cache='+str(out/'repositories')], cwd=w, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=240)
rows = []
for repetition in range(a.repetitions):
    for mode in (['explicit', 'facade'] if repetition % 2 == 0 else ['facade', 'explicit']):
        name = f'{mode}-{repetition}'
        bep = out / (name + '.bep.json')
        start = time.perf_counter()
        command = [bazel, '--batch', '--host_jvm_args=-Xmx1024m', '--output_base='+str(out/name), '--ignore_all_rc_files', 'build', '//:'+mode, '--nobuild', '--lockfile_mode=off', '--build_event_json_file='+str(bep), '--repository_cache='+str(out/'repositories')]
        with (out / (name + '.log')).open('w') as log:
            subprocess.run(command, cwd=w, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=240)
        metrics = next(row['buildMetrics'] for row in (json.loads(line) for line in bep.read_text().splitlines()) if 'buildMetrics' in row)
        rows.append(dict(mode=mode, repetition=repetition, wallSeconds=time.perf_counter()-start, metrics=metrics))
        print(name, metrics['timingMetrics'], metrics['targetMetrics'], flush=True)
summary = {mode:dict(analysisMs=statistics.median(int(row['metrics']['timingMetrics']['analysisPhaseTimeInMs']) for row in rows if row['mode']==mode), configuredTargets=statistics.median(int(row['metrics']['targetMetrics']['targetsConfigured']) for row in rows if row['mode']==mode)) for mode in ['explicit', 'facade']}
(out / 'report.json').write_text(json.dumps(dict(bazel=version,projects=a.projects,frameworks=2,repetitions=a.repetitions,summary=summary,runs=rows),indent=2)+'\n')
print(json.dumps(summary), flush=True)
