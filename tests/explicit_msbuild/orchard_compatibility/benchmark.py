"""Full pinned Orchard build measurements; setup/restore inventory is untimed.

Run inside the qualified Linux worker container after full_graph.py. Each invocation
measures one variant with cold outputs/workers, warm filesystem/package caches.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

source = Path(sys.argv[1]).resolve()
evidence = Path(sys.argv[2]).resolve()
variant = sys.argv[3]
evidence.mkdir(parents=True, exist_ok=True)
base = Path('/tmp/orchard-explicit-base')
sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
bazel = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base='+str(base), '--ignore_all_rc_files']
flags = ['--repository_cache=/tmp/repository-cache', '--disk_cache=', '--jobs=4', '--strategy=MSBuildAssembly=worker', '--worker_max_instances=MSBuildAssembly='+os.environ.get('ORCHARD_WORKERS', '2'), '--noshow_progress', '--color=no', '--curses=no']
rows = []

def run(case, command):
    start = time.perf_counter()
    with (evidence/(variant+'-'+case+'.log')).open('w') as log:
        p = subprocess.run(list(map(str, command)), cwd=source, stdout=log, stderr=subprocess.STDOUT, timeout=900)
    elapsed = time.perf_counter()-start
    if p.returncode:
        raise RuntimeError(f'{case} failed; see log')
    return elapsed

def build(case):
    elapsed = run(case, bazel+['build', '//:OrchardCore.Cms.Web', '--profile='+str(evidence/(variant+'-'+case+'.profile.gz'))]+flags)
    row = dict(case=case, seconds=elapsed)
    rows.append(row)
    (evidence/(variant+'-results.json')).write_text(json.dumps(rows, indent=2))
    print(row, flush=True)

run('shutdown-raw', [sdk/'dotnet', 'build-server', 'shutdown'])
run('clean', bazel+['clean'])
run('shutdown', bazel+['shutdown'])
# Profiling evaluation changes execution cost; regular runs disable it.
build_file = source/'BUILD.bazel'
build_file.write_text(build_file.read_text().replace('profile_build=True', 'profile_build=False'))
build('cold')
workers = [dict(json.loads(p.read_text()), project=p.parent.name) for p in (source/'bazel-bin').glob('*.diagnostics/worker.json')]
assert len(workers) == 202, len(workers)
(evidence/(variant+'-workers.json')).write_text(json.dumps(workers, indent=2))
references = {p.parent.name+'/'+p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (source/'bazel-bin').glob('*.reference/*.dll')}
(evidence/(variant+'-references.json')).write_text(json.dumps(references, indent=2))
build('noop')
edit = source/'src/OrchardCore/OrchardCore.Abstractions/Extensions/Manifests/NotFoundManifestInfo.cs'
original = edit.read_text()
reference = source/'bazel-bin/OrchardCore.Abstractions.reference/OrchardCore.Abstractions.dll'
before = reference.read_bytes()
try:
    assert 'string Description => null;' in original
    edit.write_text(original.replace('string Description => null;', 'string Description => "benchmark";'))
    build('body-edit')
    assert reference.read_bytes() == before, 'Body edit changed reference assembly'
finally:
    edit.write_text(original)
run('shutdown-final', bazel+['shutdown'])
if '--raw' in sys.argv:
    inventory = json.loads((evidence/'full-evaluated.json').read_text())
    for row in inventory:
        for name in ('bin', 'obj'):
            shutil.rmtree(source/Path(row['project']).parent/name, ignore_errors=True)
    command = [sdk/'dotnet', 'build', 'src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj', '-c', 'Release', '-m:4', '-p:RestoreSources=/tmp/feed', '-p:RestorePackagesPath=/tmp/nuget', '-p:NuGetAudit=false']
    for case in ('raw-cold', 'raw-noop', 'raw-body-edit'):
        try:
            if case == 'raw-body-edit':
                edit.write_text(original.replace('string Description => null;', 'string Description => "benchmark";'))
            elapsed = run(case, command)
            rows.append(dict(case=case, seconds=elapsed))
            (evidence/(variant+'-results.json')).write_text(json.dumps(rows, indent=2))
            print(rows[-1], flush=True)
        finally:
            edit.write_text(original)
    run('raw-final-shutdown', [sdk/'dotnet', 'build-server', 'shutdown'])
