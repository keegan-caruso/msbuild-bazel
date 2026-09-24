"""Measure an embedded module resource edit, including reference churn."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

source = Path(sys.argv[1]).resolve()
evidence = Path(sys.argv[2]).resolve()
base = '/tmp/orchard-explicit-base'
startup = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base='+base, '--ignore_all_rc_files']
flags = ['--jobs=4', '--disk_cache=', '--repository_cache=/tmp/repository-cache', '--strategy=MSBuildAssembly=worker', '--worker_max_instances=MSBuildAssembly=2', '--noshow_progress', '--color=no', '--curses=no']
def run(case, args):
    start = time.perf_counter()
    with (evidence/(case+'.log')).open('w') as log:
        p = subprocess.run(startup+args, cwd=source, stdout=log, stderr=subprocess.STDOUT, timeout=600)
    elapsed = time.perf_counter()-start
    assert p.returncode == 0, case
    return elapsed
path = source/'src/OrchardCore.Modules/OrchardCore.Setup/wwwroot/Styles/setup.min.css'
original = path.read_bytes()
reference = source/'bazel-bin/OrchardCore.Setup.reference/OrchardCore.Setup.dll'
try:
    run('resource-warmup', ['build', '//:OrchardCore.Cms.Web']+flags)
    before = hashlib.sha256(reference.read_bytes()).hexdigest()
    path.write_bytes(original+b'\n/* benchmark-resource */\n')
    seconds = run('resource-edit', ['build', '//:OrchardCore.Cms.Web']+flags)
    after = hashlib.sha256(reference.read_bytes()).hexdigest()
    log = (evidence/'resource-edit.log').read_text()
    projects = re.findall(r'INFO: From MSBuildAssembly (.*?).reference/', log)
    result = dict(seconds=seconds, referenceChanged=before != after, projects=projects)
    (evidence/'resource-edit.json').write_text(json.dumps(result, indent=2))
    print(result, flush=True)
finally:
    path.write_bytes(original)
    run('resource-final-shutdown', ['shutdown'])

if '--skip-raw' in sys.argv:
    sys.exit(0)

sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
raw = [str(sdk/'dotnet'), 'build', 'src/OrchardCore.Cms.Web/OrchardCore.Cms.Web.csproj', '-c', 'Release', '-m:4', '-p:RestoreSources=/tmp/feed', '-p:RestorePackagesPath=/tmp/nuget', '-p:NuGetAudit=false']
def raw_run(name):
    start = time.perf_counter()
    with (evidence/(name+'.log')).open('w') as log:
        p = subprocess.run(raw, cwd=source, stdout=log, stderr=subprocess.STDOUT, timeout=600)
    assert p.returncode == 0, name
    return time.perf_counter()-start
try:
    raw_run('raw-resource-warmup')
    path.write_bytes(original+b'\n/* benchmark-resource */\n')
    result['rawSeconds'] = raw_run('raw-resource-edit')
    (evidence/'resource-edit.json').write_text(json.dumps(result, indent=2))
    print(result, flush=True)
finally:
    path.write_bytes(original)
    subprocess.run([str(sdk/'dotnet'), 'build-server', 'shutdown'], check=True)
