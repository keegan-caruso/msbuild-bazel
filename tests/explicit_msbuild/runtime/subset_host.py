"""Compose the source-built managed closure and native outputs into a declared host."""
import ast
import json
import os
from pathlib import Path
import shutil
import sys

workspace=Path(sys.argv[1]).resolve();native=Path(sys.argv[2]).resolve()
here=Path(__file__).resolve().parent
selection=json.loads((workspace/'host-selection.json').read_text())
assert set(selection)=={'hostFrameworks','privateFrameworks'}, selection
def copy_input(src,dst):
    # Large immutable toolchain inputs may be shared inside this fixture only.
    if Path(src).name in ['toolchain.tar','bwrap']:
        try:
            os.link(src,dst)
            return dst
        except OSError:pass
    return shutil.copy2(src,dst)
shutil.copytree(native,workspace/'native',copy_function=copy_input)
shutil.copyfile(here/'NativeBuild.cs.txt',workspace/'native/NativeBuild.cs')
shutil.copyfile(here/'native_action.bzl',workspace/'native/native_action.bzl')
probe=workspace/'load_probe';probe.mkdir()
shutil.copyfile(here/'SubsetProbe.cs.txt',probe/'StartupHook.cs')
(probe/'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
(probe/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_library")\nmsbuild_library(name="probe",project="Probe.csproj",srcs=["StartupHook.cs"],target_framework="net10.0",linux_worker=True,visibility=["//runtime:__pkg__"])\n')
shared='shared/Microsoft.NETCore.App/10.0.11'
native_replacements={'libcoreclr.so':'//native:coreclr','libclrjit.so':'//native:jit'}
native_paths={name:shared+'/'+name for name in native_replacements}
for component in map(Path,sys.argv[3:]):
    destination=workspace/component.name
    shutil.copytree(component,destination,copy_function=copy_input)
    products=json.loads((component/'products.json').read_text())
    for group,name in products['products'].items():
        native_replacements[name]='//'+component.name+':'+group
        native_paths[name]=products['destinations'][name]
upstream=workspace/'upstream/BUILD.bazel';lines=upstream.read_text().splitlines();replacements={};private={};tests=[]
for i,line in enumerate(lines):
    if not line.startswith(('msbuild_library(', 'msbuild_test(')):continue
    args={kw.arg:ast.literal_eval(kw.value) for kw in ast.parse(line).body[0].value.keywords}
    if line.startswith('msbuild_test('):tests.append({'label':'//upstream:'+args['name'],'assembly':args['assembly_name'],'framework':args['target_framework'],'project':args['project'],'settings':args.get('test_settings')});continue
    project=args['project']
    if args['output_mode']!='implementation' or args['target_framework'].startswith('netstandard'):continue
    if not (project.startswith('src/coreclr/System.Private.CoreLib/') or (project.startswith('src/libraries/') and '/src/' in project and (workspace/'runtime'/shared/(args['assembly_name']+'.dll')).is_file())):continue
    assembly=args['assembly_name'];framework=args['target_framework']
    if framework.split('-')[0]!='net10.0':
        if selection['privateFrameworks'].get(assembly)!=framework:continue
    elif assembly in selection['hostFrameworks'] and selection['hostFrameworks'][assembly]!=framework:continue
    name=assembly+'.dll'
    destination=replacements if args['target_framework'].split('-')[0]=='net10.0' else private
    assert name not in destination,name
    destination[name]='//upstream:'+args['name']
    lines[i]=line[:-1]+',visibility=["//runtime:__pkg__"])'
upstream.write_text('\n'.join(lines)+'\n')
host=workspace/'runtime'
paths={str(p.relative_to(host)):str(p.relative_to(host)) for p in host.rglob('*') if p.is_file() and p.name!='BUILD.bazel' and p.name not in replacements and p.name not in native_replacements}
paths.update({label:shared for label in replacements.values()})
paths.update({label:'private' for label in private.values()})
for name,label in native_replacements.items():paths[label]=native_paths[name]
paths['//load_probe:probe']='probe'
wrapper=host/'host.sh'
wrapper.write_text('''#!/bin/sh
set -eu
ulimit -c 0
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export DOTNET_ROOT="$root"
export DOTNET_ReadyToRun=0
export DOTNET_STARTUP_HOOKS="$root/probe/Probe.dll"
export QUALIFICATION_HOST_ROOT="$root"
exec "$root/dotnet" "$@"
''');wrapper.chmod(0o755)
paths['host.sh']='host.sh'
inventory={p.name:str(p.relative_to(host)) for p in (host/shared).iterdir() if p.is_file() and (p.suffix in ['.dll','.so'])}
inventory.update({'dotnet':'dotnet','libhostfxr.so':'host/fxr/10.0.11/libhostfxr.so'})
inventory.update(native_paths)
inventory={name:[path] for name,path in inventory.items()}
for name in private:inventory.setdefault(name,[]).append('private/'+name)
(host/'runtime-inventory.json').write_text(json.dumps(inventory,indent=2)+'\n');paths['runtime-inventory.json']='runtime-inventory.json'
(host/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_layout","msbuild_runtime")\nmsbuild_layout(name="tree",paths='+json.dumps(paths)+')\nmsbuild_runtime(name="host",layout=":tree",entry_point="host.sh",visibility=["//visibility:public"])\n')
(workspace/'subset.json').write_text(json.dumps({'managed':replacements,'private':private,'native':native_replacements,'nativePaths':native_paths,'tests':tests,'installed':[name for name in inventory if name not in replacements and name not in native_replacements]},indent=2)+'\n')
print('Declared',len(replacements),'source-built framework replacements and',len(tests),'test projects',flush=True)
