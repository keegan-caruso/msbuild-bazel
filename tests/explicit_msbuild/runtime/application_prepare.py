"""Prepare pinned source-runtime producers and an ordinary SDK-style app.

This Linux ARM64 qualification uses the existing runtime inventory adapter.
Setup restores/evaluates upstream projects; Bazel builds all declared products.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('source', type=Path)
p.add_argument('output', type=Path)
a = p.parse_args()
source = a.source.resolve()
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
here = Path(__file__).resolve().parent
rules = here.parents[2]
sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
sdk_version = json.loads((rules/'global.json').read_text())['sdk']['version']
records = []
selection = json.loads((here/'subset_slices.json').read_text())
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=source, text=True).strip() == selection['commit']


def run(name, command, cwd=out):
    start = time.monotonic()
    with (out/(name+'.log')).open('w') as log:
        result = subprocess.run(list(map(str, command)), cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    records.append(dict(stage=name, seconds=round(time.monotonic()-start, 3), exitCode=result.returncode))
    (out/'stages.json').write_text(json.dumps(records, indent=2)+'\n')
    print(name, result.returncode, flush=True)
    result.check_returncode()


# Preserve the previously qualified runtime component selection, without its
# test projects, test runners or private test formatter.
entries = []
for part in selection['slices']:
    entries = [e for e in entries if e['project'] not in part.get('removeRoots', [])]
    for entry in part['entries']:
        value = dict(project=entry, framework=part['framework']) if isinstance(entry, str) else entry
        if '/tests/' not in value['project']:
            entries.append(value)
# CoreLib is reached through the upstream references. Adding it as a root
# with TargetFramework forced creates a second, different global configuration.
entries = list({(e['project'], e['framework']): e for e in entries}.values())
probe = out/'inventory'
probe.mkdir()
(probe/'selection.json').write_text(json.dumps(dict(entries=entries, hostFrameworks=selection['hostFrameworks'], privateFrameworks={}), indent=2)+'\n')
# Bootstrap the upstream evaluation prerequisites. These raw outputs are never
# copied into the generated Bazel workspace by prepare.py.
root = ET.Element('Project')
items = ET.SubElement(root, 'ItemGroup')
for entry in entries:
    item = ET.SubElement(items, 'RuntimeProject', Include=str(source/entry['project']))
    ET.SubElement(item, 'AdditionalProperties').text = 'TargetFramework='+entry['framework']
target = ET.SubElement(root, 'Target', Name='Build')
properties = 'Configuration=Release;TargetArchitecture=arm64;TargetOS=linux;UseLocalTargetingRuntimePack=false;RestoreUseStaticGraphEvaluation=false;NuGetAudit=false;NetCoreSdkRoot='+str(sdk/'sdk'/sdk_version)
ET.SubElement(target, 'MSBuild', Projects='@(RuntimeProject)', Targets='Build', BuildInParallel='true', Properties=properties)
# Restore outer builds so platform frameworks do not leak into build tools.
for index, entry in enumerate(entries):
    run('restore-'+str(index), [sdk/'dotnet', 'msbuild', source/entry['project'], '-t:Restore', *['-p:'+value for value in properties.split(';')]], source)
ET.ElementTree(root).write(out/'bootstrap.proj')
run('bootstrap', [sdk/'dotnet', 'msbuild', out/'bootstrap.proj', '-t:Build', '-m:2', '-nologo'])
for name, destination in [('Inventory.cs.txt', 'Program.cs'), ('Inventory.csproj.txt', 'Inventory.csproj')]:
    shutil.copyfile(here/name, probe/destination)
run('inventory-build', [sdk/'dotnet', 'build', probe/'Inventory.csproj', '-c', 'Release'])
run('inventory', [sdk/'dotnet', probe/'bin/Release/net10.0/Inventory.dll', source, probe/'selection.json', probe/'inventory.json'])
w = out/'workspace'
run('declarations', [os.sys.executable, here/'prepare.py', source, probe/'inventory.json', w, rules])
# subset_host.py uses this temporary inventory to select framework assemblies.
# source_host.py subsequently removes every installed binary from the layout.
host = w/'runtime'
for relative in ['dotnet', 'host', 'shared/Microsoft.NETCore.App']:
    src, dst = sdk/relative, host/relative
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, copy_function=os.link)
    else:
        os.link(src, dst)
inputs = out/'native-inputs'
inputs.mkdir()
run('native-inputs', [os.sys.executable, here/'native_prepare.py', source, inputs])
components = []
for component in ['support', 'host', 'crypto', 'compression']:
    destination = inputs/('native_'+component)
    run('native-'+component, [os.sys.executable, here/'native_component_prepare.py', inputs/'native', destination, component])
    components.append(destination)
run('host', [os.sys.executable, here/'subset_host.py', w, inputs/'native', *components])
run('source-only-host', [os.sys.executable, here/'source_host.py', w])
with (host/'BUILD.bazel').open('a') as build:
    build.write('\nmsbuild_runtime(name="app_host",layout=":tree",entry_point="dotnet",runtime_identifier="linux-arm64",version="10.0.0",visibility=["//visibility:public"])\n')
shutil.copytree(rules/'examples/source-runtime-app', w/'app')
shutil.copyfile(rules/'.bazelversion', w/'.bazelversion')
print('Prepared application workspace:', w, flush=True)
