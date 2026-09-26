"""Matched two-slot Orchard workflow timings on the qualified generated graph.

Inputs/SDK/package downloads must already exist. Cold means clean action/build
outputs and stopped compiler servers, not an empty filesystem or network cache.
This driver runs sequentially and restores every source/mapping edit.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('workspace', type=Path)
p.add_argument('raw', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--repetitions', type=int, default=3)
p.add_argument('--workers', type=int, choices=[1, 2], default=2)
p.add_argument('--profile-control', action='store_true', help='Also time detailed MSBuild profiling, alternating order')
p.add_argument('--phase', choices=['bazel', 'raw'], required=True)
a = p.parse_args()
w, raw, out = [v.resolve() for v in [a.workspace, a.raw, a.output]]
out.mkdir(parents=True, exist_ok=True)
base = out / 'base'
bazel = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base=' + str(base), '--host_jvm_args=-Xmx1536m', '--ignore_all_rc_files']
dotnet = str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']) / 'dotnet')
flags = ['--jobs=2', '--worker_max_instances=MSBuildAssembly=' + str(a.workers), '--experimental_total_worker_memory_limit_mb=4096', '--experimental_shrink_worker_pool', '--experimental_worker_metrics_poll_interval=1s', '--disk_cache=', '--remote_cache=', '--noshow_progress', '--color=no', '--curses=no']
target = '//:src_OrchardCore.Cms.Web_OrchardCore.Cms.Web'
project = 'src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj'
relative = 'src/OrchardCore/OrchardCore.Abstractions/Extensions/Manifests/NotFoundManifestInfo.cs'
rows = []
def command(name, cmd, cwd, record=True):
    began = time.monotonic()
    with (out / (name + '.log')).open('w') as log:
        result = subprocess.run([str(v) for v in cmd], cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    seconds = round(time.monotonic() - began, 3)
    assert result.returncode == 0, (name, result.returncode, out / (name + '.log'))
    if record:
        row = dict(case=name, seconds=seconds)
        rows.append(row); save(); print(row, flush=True)
        return row

def save():
    (out / (a.phase + '-results.json')).write_text(json.dumps(dict(phase=a.phase, slots=2, workers=a.workers, workerMemoryMb=4096, profileControl=a.profile_control, repetitions=a.repetitions, records=rows), indent=2) + '\n')

def build(name):
    execution = out / (name + '.execution.json')
    row = command(name, bazel + ['build', target, *flags, '--execution_log_json_file=' + str(execution), '--profile=' + str(out / (name + '.profile.gz'))], w)
    text = execution.read_text(); decoder = json.JSONDecoder(); counts = Counter(); durations = Counter(); offset = 0
    while offset < len(text):
        if text[offset].isspace():
            offset += 1
            continue
        action, offset = decoder.raw_decode(text, offset)
        if not action.get('cacheHit'):
            counts[action.get('mnemonic')] += 1
            # Per-action cumulative time is not wall time: two slots overlap.
            total = action.get('metrics', {}).get('totalTime', '0s')
            durations[action.get('mnemonic')] += float(total.removesuffix('s'))
    row.update(executed=dict(counts), cumulativeActionSeconds=dict(durations)); save()
    return row

source = (w if a.phase == 'bazel' else raw) / relative
original = source.read_bytes()
mapfile = w / 'sync.json'; mapping_original = mapfile.read_bytes()
generated_original = (w / 'projects.generated.bzl').read_bytes()
def edit(kind, repetition):
    text = original.decode()
    if kind == 'body':
        assert 'string Description => null;' in text
        text = text.replace('string Description => null;', 'string Description => "workflow-' + str(repetition) + '";')
    else:
        assert 'public bool Exists => false;' in text
        text = text.replace('public bool Exists => false;', 'public bool Exists => false;\n    public bool WorkflowApi' + str(repetition) + ' => true;')
    source.write_text(text)
try:
    if a.phase == 'bazel':
        command('initial-sync', bazel + ['run', '//:sync', '--jobs=2'], w)
        for i in range(a.repetitions):
            command('unchanged-sync-' + str(i), bazel + ['run', '//:sync', '--', '--check'], w)
        # Alternate the order to expose warm-filesystem/order effects.
        for i in range(a.repetitions):
            for enabled in (([True, False] if i % 2 == 0 else [False, True]) if a.profile_control else [False]):
                variant = 'profiled' if enabled else 'normal'
                mapping = json.loads(mapping_original)
                mapping.setdefault('projectDefaults', {})['profileBuild'] = enabled
                for binding in mapping['projects'].values(): binding.pop('profileBuild', None)
                mapfile.write_text(json.dumps(mapping, indent=2) + '\n')
                command('configure-' + variant + '-' + str(i), bazel + ['run', '//:sync'], w, False)
                command('clean-' + variant + '-' + str(i), bazel + ['clean'], w, False)
                command('shutdown-' + variant + '-' + str(i), bazel + ['shutdown'], w, False)
                row = build(variant + '-cold-' + str(i))
                assert row['executed'].get('MSBuildAssembly') == 202, row
                if not enabled:
                    for kind in ['noop', 'body', 'api']:
                        if kind != 'noop': edit(kind, i)
                        result = build(kind + '-' + str(i))
                        expected = {'noop': 0, 'body': 1, 'api': 193}[kind]
                        assert result['executed'].get('MSBuildAssembly', 0) == expected, result
                        if kind != 'noop':
                            source.write_bytes(original)
                            if kind == 'body':
                                build(kind + '-repair-' + str(i))
                command('stop-' + variant + '-' + str(i), bazel + ['shutdown'], w, False)
                subprocess.run(['fstrim', '/'], check=True, stdout=subprocess.DEVNULL)
    else:
        common = [dotnet, 'build', project, '-c', 'Release', '-m:2', '--no-restore', '-p:NuGetAudit=false']
        for i in range(a.repetitions):
            command('raw-clean-' + str(i), [dotnet, 'clean', project, '-c', 'Release', '-m:2'], raw, False)
            command('raw-stop-' + str(i), [dotnet, 'build-server', 'shutdown'], raw, False)
            command('raw-restore-' + str(i), [dotnet, 'restore', project, '--force', '-p:NuGetAudit=false', '-p:RestorePackagesPath=/tmp/nuget', '-m:2'], raw)
            command('raw-cold-' + str(i), common, raw)
            for kind in ['noop', 'body', 'api']:
                if kind != 'noop': edit(kind, i)
                command('raw-' + kind + '-' + str(i), common, raw)
                if kind != 'noop':
                    source.write_bytes(original)
                    if kind == 'body':
                        command('raw-' + kind + '-repair-' + str(i), common, raw, False)
            command('raw-stop-final-' + str(i), [dotnet, 'build-server', 'shutdown'], raw, False)
            subprocess.run(['fstrim', '/'], check=True, stdout=subprocess.DEVNULL)
finally:
    source.write_bytes(original)
    mapfile.write_bytes(mapping_original)
    (w / 'projects.generated.bzl').write_bytes(generated_original)
    subprocess.run(bazel + ['shutdown'], cwd=w, check=True)
    subprocess.run([dotnet, 'build-server', 'shutdown'], cwd=raw, check=True)
