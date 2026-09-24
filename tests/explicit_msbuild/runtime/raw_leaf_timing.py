"""Time raw MSBuild body edits over the qualified runtime slice's configured roots.

Requires a pristine pinned upstream checkout with outputs already primed using
subset_prepare.py's raw commands, and its cumulative inventory/selection files.
Restore, initial compilation and the binlog reader build are outside samples.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET

from timing_tools import verify_tools

p = argparse.ArgumentParser(description=__doc__)
for name in ['source', 'inventory', 'report']:
    p.add_argument(name, type=Path)
p.add_argument('--repetitions', type=int, default=3)
p.add_argument('--shared-compilation', choices=['true', 'false'], default='false')
a = p.parse_args()
assert a.repetitions >= 3
source = a.source.resolve()
out = a.report.resolve()
assert not out.is_relative_to(source), 'Keep reports outside the upstream checkout'
out.mkdir(parents=True, exist_ok=False)
shutil.copyfile(Path(__file__), out/'harness.py')
shutil.copyfile(Path(__file__).with_name('timing_tools.py'), out/'timing_tools.py')
(out/'toolchain.json').write_text(json.dumps(verify_tools(cwd=out), indent=2)+'\n')
here = Path(__file__).resolve().parent
sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
selection = json.loads((a.inventory.parent/'selection.json').read_text())
rows = json.loads(a.inventory.read_text())
commit = json.loads((here/'subset_slices.json').read_text())['commit']
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip() == commit
assert not subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=source)
entry = 'src/libraries/System.IO.Pipelines/src/System.IO.Pipelines.csproj'
contract = 'src/libraries/System.IO.Pipelines/ref/System.IO.Pipelines.csproj'
assert {'project': entry, 'framework': 'net10.0'} in selection['entries']

def output_for(project):
    row = next(r for r in rows if r['project'] == project and r['framework'] == 'net10.0')
    # Inventory paths belong to the qualification checkout. Relocate its
    # artifacts subtree to the raw checkout supplied to this invocation.
    path = row['properties']['OutputPath'].split('/artifacts/', 1)[1]
    return source/'artifacts'/path/'System.IO.Pipelines.dll'

implementation = output_for(entry)
reference = output_for(contract)
assert implementation.is_file() and reference.is_file(), 'Prime raw outputs first'
project = ET.Element('Project')
group = ET.SubElement(project, 'ItemGroup')
for item in selection['entries']:
    node = ET.SubElement(group, 'SelectedProject', Include=str(source/item['project']))
    ET.SubElement(node, 'AdditionalProperties').text = 'TargetFramework='+item['framework']
target = ET.SubElement(project, 'Target', Name='Build')
ET.SubElement(target, 'MSBuild', Projects='@(SelectedProject)', Targets='Build', BuildInParallel='true')
ET.indent(project)
traversal = out/'selected.proj'
ET.ElementTree(project).write(traversal, encoding='unicode')
reader = out/'reader'
reader.mkdir()
shutil.copyfile(here/'Inventory.csproj.txt', reader/'Reader.csproj')
shutil.copyfile(here/'RawTimingLog.cs.txt', reader/'Program.cs')
with (out/'reader-build.log').open('w') as log:
    subprocess.run([sdk/'dotnet', 'build', reader/'Reader.csproj', '-c', 'Release'],
                   stdout=log, stderr=subprocess.STDOUT, check=True)
reader_dll = reader/'bin/Release/net10.0/Reader.dll'
properties = ['Configuration=Release', 'TargetArchitecture=arm64', 'TargetOS=linux',
              'UseLocalTargetingRuntimePack=false', 'RestoreUseStaticGraphEvaluation=false',
              'NuGetAudit=false', 'UseSharedCompilation='+a.shared_compilation, 'NetCoreSdkRoot='+str(sdk/'sdk/10.0.400')]
command = [str(sdk/'dotnet'), 'msbuild', str(traversal), '-t:Build', '-m:2', '-nr:true',
           *['-p:'+v for v in properties]]
body = source/'src/libraries/System.IO.Pipelines/src/System/IO/Pipelines/PipeOptions.cs'
saved = body.read_bytes()
old = b'UseSynchronizationContext = useSynchronizationContext;'
assert saved.count(old) == 1
nonce = uuid.uuid4().hex
records = []

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run(case):
    cmd = command+['-bl:'+str(out/(case+'.binlog'))]
    start = time.monotonic()
    with (out/(case+'.log')).open('w') as log:
        result = subprocess.run(cmd, cwd=source, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
    wall = time.monotonic()-start
    row = dict(case=case, wallSeconds=round(wall, 3), exitCode=result.returncode, command=cmd)
    if result.returncode == 0:
        row.update(json.loads(subprocess.check_output([sdk/'dotnet', reader_dll, out/(case+'.binlog')], text=True)))
        for item in row['compiled']:
            item['project'] = str(Path(item['project']).relative_to(source))
        row['implementationSha256'] = digest(implementation)
        row['referenceSha256'] = digest(reference)
    records.append(row)
    (out/'report.json').write_text(json.dumps(dict(commit=commit, nonce=nonce, roots=selection['entries'], records=records), indent=2)+'\n')
    print({k: v for k, v in row.items() if k not in ['command']}, flush=True)
    result.check_returncode()
    return row

try:
    run('prime')
    original = digest(implementation)
    public = digest(reference)
    previous = original
    for i in range(a.repetitions):
        run('noop-'+str(i))
        replacement = old+(' GC.KeepAlive("raw-leaf-timing-'+nonce+'-'+str(i)+'");').encode()
        body.write_bytes(saved.replace(old, replacement))
        row = run('edit-'+str(i))
        assert any(c['project'] == entry for c in row['compiled']), 'Edited producer did not compile'
        assert digest(reference) == public, 'Public contract changed'
        assert digest(implementation) != previous, 'Implementation output unchanged'
        previous = digest(implementation)
    body.write_bytes(saved)
    run('restore')
    assert digest(implementation) == original and digest(reference) == public, 'Restored output differs'
finally:
    if body.read_bytes() != saved:
        body.write_bytes(saved)
summary = {kind: {'wallMedianSeconds': statistics.median(r['wallSeconds'] for r in records if r['case'].startswith(kind+'-')),
                  'samples': [r['wallSeconds'] for r in records if r['case'].startswith(kind+'-')]}
           for kind in ['noop', 'edit']}
(out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
print(summary, flush=True)
