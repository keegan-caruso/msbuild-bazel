"""Measure merged reference inference on Orchard, then probe library opt-outs.

Uses disposable, already restored generated/raw workspaces. Restores all edited
source, mapping and generated files. A failed opt-out probe is evidence, not a
reason to remove required references or relax compiler errors.
"""
import argparse
import ast
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import tarfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('workspace', type=Path)
p.add_argument('raw', type=Path)
p.add_argument('output', type=Path)
p.add_argument('--repetitions', type=int, default=3)
p.add_argument('--sample-offset', type=int, default=0)
p.add_argument('--probe-only', action='store_true', help='Only test explicit library opt-outs; do not repeat timing samples')
p.add_argument('--state', type=Path, help='Reuse a completed run output base/cache; use a fresh sample offset')
a = p.parse_args()
w, raw, out = [v.resolve() for v in [a.workspace, a.raw, a.output]]
out.mkdir(parents=True, exist_ok=False)
state = a.state.resolve() if a.state else out
bazel = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base=' + str(state / 'base'), '--host_jvm_args=-Xmx1536m', '--ignore_all_rc_files']
dotnet = str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']) / 'dotnet')
flags = ['--jobs=2', '--worker_max_instances=MSBuildAssembly=2', '--experimental_total_worker_memory_limit_mb=4096', '--experimental_shrink_worker_pool', '--experimental_worker_metrics_poll_interval=1s', '--disk_cache=' + str(state / 'cache'), '--remote_cache=', '--remote_download_outputs=all', '--noshow_progress', '--color=no', '--curses=no']
target = '//:src_OrchardCore.Cms.Web_OrchardCore.Cms.Web'
project = 'src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj'
relative = 'src/OrchardCore/OrchardCore.Abstractions/Extensions/Manifests/NotFoundManifestInfo.cs'
core = 'src_OrchardCore_OrchardCore.Abstractions_OrchardCore.Abstractions_net10_0'
files = [w / relative, raw / relative, w / 'sync.json', w / 'projects.generated.bzl']
originals = {f: f.read_bytes() for f in files}
assert originals[w / relative] == originals[raw / relative]
report = {'repetitions': a.repetitions, 'sampleOffset': a.sample_offset, 'records': [], 'inputHashes': {str(f): hashlib.sha256(b).hexdigest() for f, b in originals.items()}}
with tarfile.open(out / 'inputs-before.tar.gz', 'w:gz') as archive:
    for index, path in enumerate(files):
        archive.add(path, arcname=str(index) + '-' + path.name)
os.sync()

def save():
    (out / 'results.json').write_text(json.dumps(report, indent=2) + '\n')

def run(name, args, cwd, success=True):
    print('Running ' + name, flush=True)
    began = time.monotonic()
    with (out / (name + '.log')).open('w') as log:
        result = subprocess.run(args, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    row = {'case': name, 'seconds': round(time.monotonic() - began, 3), 'exitCode': result.returncode}
    report['records'].append(row)
    save()
    # Reclaim deleted guest blocks between commands, outside measured wall time.
    subprocess.run(['fstrim', '/'], check=True, stdout=subprocess.DEVNULL)
    if success:
        assert result.returncode == 0, (name, out / (name + '.log'))
    return row

def hashes(root, pattern):
    return {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in root.glob(pattern)}

def bazel_build(name, probe=False):
    execution = out / (name + '.execution.json')
    row = run(name, bazel + ['build', target, *flags, '--execution_log_json_file=' + str(execution), '--profile=' + str(out / (name + '.profile.gz'))], w, not probe)
    text = execution.read_text()
    offset = 0
    decoder = json.JSONDecoder()
    compiled = []
    durations = []
    while offset < len(text):
        if text[offset].isspace():
            offset += 1
            continue
        action, offset = decoder.raw_decode(text, offset)
        if action.get('mnemonic') == 'MSBuildAssembly' and not action.get('cacheHit'):
            compiled.append(action['targetLabel'].split(':')[1])
            durations.append(float(action.get('metrics', {}).get('totalTime', '0s').removesuffix('s')))
    row['compiled'] = sorted(set(compiled))
    row['cumulativeCompileSeconds'] = round(sum(durations), 3)
    save()
    with execution.open('rb') as source, gzip.open(str(execution) + '.gz', 'wb') as dest:
        shutil.copyfileobj(source, dest)
    execution.unlink()
    subprocess.run(['fstrim', '/'], check=True, stdout=subprocess.DEVNULL)
    return row

raw_command = [dotnet, 'build', project, '-c', 'Release', '-m:2', '--no-restore', '-p:NuGetAudit=false']
def smoke(name, raw_mode=False):
    script = Path(__file__).resolve().parents[2] / 'explicit_msbuild/orchard_compatibility/smoke.py'
    run(name, [sys.executable, str(script), str(raw if raw_mode else w), str(out), name, *(['--raw'] if raw_mode else ['--target', target.split(':')[1]])], w)
    return json.loads((out / (name + '.json')).read_text())

try:
    if not a.probe_only:
        run('merged-sync-check', bazel + ['run', '//:sync', '--jobs=2', '--', '--check'], w)
        assert (w / 'projects.generated.bzl').read_bytes() == originals[w / 'projects.generated.bzl']
        report['generatedBytesUnchanged'] = True
        mapping = json.loads(originals[w / 'sync.json'])
        mapping.setdefault('projectDefaults', {})['profileBuild'] = False
        for binding in mapping['projects'].values():
            binding.pop('profileBuild', None)
        (w / 'sync.json').write_text(json.dumps(mapping, indent=2) + '\n')
        run('configure-unprofiled', bazel + ['run', '//:sync', '--jobs=2'], w)
        bazel_build('warmup-bazel')
        run('warmup-raw', raw_command + ['-t:Rebuild'], raw)
        before = hashes(w / 'bazel-bin', '*.reference/*.dll')
        raw_before = hashes(raw, 'src/**/obj/Release/net10.0/ref/*.dll')
        assert set(before) - set(raw_before) == {'OrchardCore.SourceGenerators.dll'}
        assert 'OrchardCore.Abstractions.dll' in before
        compared = set(before) & set(raw_before)
        report['baselineReferenceHashes'] = before
        report['baselineRawReferenceHashes'] = raw_before
        report['referenceAssemblies'] = len(before)
        report['rawComparableReferenceAssemblies'] = len(compared)
        report['rawReferenceException'] = 'SourceGenerators targets netstandard2.0 and does not emit a reference assembly; it must remain uncompiled and unchanged in these edits.'
        for i in range(a.sample_offset, a.sample_offset + a.repetitions):
            for case in ['noop', 'body', 'api']:
                text = originals[w / relative].decode()
                if case == 'body':
                    text = text.replace('string Description => null;', 'string Description => "orchard-reference-' + str(i) + '";')
                elif case == 'api':
                    text = text.replace('public bool Exists => false;', 'public bool Exists => false;\n    public bool OrchardReferenceApi' + str(i) + ' => true;')
                for root in [w, raw]:
                    (root / relative).write_text(text)
                name = case + '-' + str(i)
                if i % 2:
                    raw_row = run(name + '-raw', raw_command, raw)
                row = bazel_build(name + '-bazel')
                if not i % 2:
                    raw_row = run(name + '-raw', raw_command, raw)
                after = hashes(w / 'bazel-bin', '*.reference/*.dll')
                raw_after = hashes(raw, 'src/**/obj/Release/net10.0/ref/*.dll')
                row['changedReferences'] = sorted(k for k in before if after[k] != before[k])
                raw_row['changedReferences'] = sorted(k for k in compared if raw_after[k] != raw_before[k])
                row['referenceChangePatternMatchesRaw'] = row['changedReferences'] == raw_row['changedReferences']
                if case != 'api':
                    assert row['referenceChangePatternMatchesRaw'], name
                expected = 0 if case == 'noop' else 1 if case == 'body' else 193
                assert len(row['compiled']) == expected, (name, len(row['compiled']))
                if case == 'body':
                    assert row['compiled'] == [core] and not row['changedReferences']
                if case == 'api':
                    assert 'OrchardCore.Abstractions.dll' in row['changedReferences']
                save()
                print(name, row['seconds'], raw_row['seconds'], 'compilations', len(row['compiled']), 'changed refs', len(row['changedReferences']), flush=True)
                if case != 'noop':
                    for root in [w, raw]:
                        (root / relative).write_bytes(originals[root / relative])
                    reverted = bazel_build(name + '-revert-bazel')
                    assert not reverted['compiled']
                    run(name + '-revert-raw', raw_command, raw)
                    # Orchard's interceptor generator uses GUIDs, so raw recompilation
                    # can change references even after restoring identical sources.
                    raw_before = hashes(raw, 'src/**/obj/Release/net10.0/ref/*.dll')
        bazel_smoke = smoke('baseline-bazel-smoke')
        raw_smoke = smoke('baseline-raw-smoke', True)
        assert [r['sha256'] for r in bazel_smoke[1:]] == [r['sha256'] for r in raw_smoke[1:]]
        report['smokeEndpointsPerBuildSystem'] = 4
        report['rawAssetHashesMatch'] = True
    else:
        mapping = json.loads(originals[w / 'sync.json'])
    # Use the supported mapping for library compiler inputs; keep binary manifests transitive.
    projects = {}
    for node in ast.walk(ast.parse((w / 'projects.generated.bzl').read_text())):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'msbuild_project':
            attrs = {k.arg: ast.literal_eval(k.value) for k in node.keywords}
            projects[attrs['project']] = attrs
    for path in projects:
        binding = mapping['projects'][path]
        binding['transitiveCompileReferences'] = False
    report['optedOutLibraries'] = len(projects)
    (w / 'sync.json').write_text(json.dumps(mapping, indent=2) + '\n')
    run('optout-sync', bazel + ['run', '//:sync', '--jobs=2'], w)
    probe = bazel_build('optout-bazel', True)
    raw_probe = run('optout-raw', raw_command + ['-p:DisableTransitiveProjectReferences=true'], raw, False)
    for row in [probe, raw_probe]:
        log = (out / (row['case'] + '.log')).read_text()
        row['diagnostics'] = sorted(set(re.findall(r'error CS\d+: [^\n]+', log)))
    report['optoutPassesWithoutNewReferences'] = probe['exitCode'] == raw_probe['exitCode'] == 0
    save()
finally:
    for path, content in originals.items():
        path.write_bytes(content)
    subprocess.run(bazel + ['shutdown'], cwd=w, check=True)
    subprocess.run([dotnet, 'build-server', 'shutdown'], cwd=raw, check=True)
