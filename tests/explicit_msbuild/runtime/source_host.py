"""Replace a prepared qualification host's SDK template with source-only products.

This is a selected runtime test host, not a complete redistributable framework.
Run after subset_host.py in a fresh disposable fixture workspace.
"""
import ast
import json
from pathlib import Path
import shutil
import sys

w=Path(sys.argv[1]).resolve();host=w/'runtime'
manifest=json.loads((w/'subset.json').read_text())
assert not manifest.get('sourceOnly'), 'Host was already converted'
required={'dotnet','libhostfxr.so','libhostpolicy.so','libcoreclr.so','libclrjit.so','libSystem.Native.so'}
assert required<=set(manifest['native']),required-set(manifest['native'])
assert 'System.Private.CoreLib.dll' in manifest['managed']
versions=list((host/'shared/Microsoft.NETCore.App').iterdir());assert len(versions)==1
old_shared=str(versions[0].relative_to(host))
version='10.0.0';shared='shared/Microsoft.NETCore.App/'+version
commit='60629d14374c56f1cb51819049ad1fa529307f8d'
old_inventory=json.loads((host/'runtime-inventory.json').read_text())
wrapper=(host/'host.sh').read_bytes()
previous_paths=next({kw.arg:ast.literal_eval(kw.value) for kw in node.value.keywords}['paths'] for node in ast.parse((host/'BUILD.bazel').read_text()).body if isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and isinstance(node.value.func,ast.Name) and node.value.func.id=='msbuild_layout')
source_labels=set(manifest['managed'].values())|set(manifest.get('private',{}).values())|set(manifest['native'].values())|{'//load_probe:probe'}
assert {p for p in previous_paths if p.startswith('//')}==source_labels
paths={label:destination.replace(old_shared,shared) for label,destination in previous_paths.items() if label in source_labels}
manifest['nativePaths']={name:path.replace(old_shared,shared) for name,path in manifest['nativePaths'].items()}
expected={name:[shared+'/'+name] for name in manifest['managed']}
for name in manifest.get('private',{}):expected.setdefault(name,[]).append('private/'+name)
for name,path in manifest['nativePaths'].items():expected.setdefault(name,[]).append(path)
for name in old_inventory:expected.setdefault(name,[])
# Empty candidate lists make the existing startup observer reject any load of
# an excluded framework component, including a copy from outside the host.
excluded=sorted(name for name,candidates in expected.items() if not candidates)
shutil.rmtree(host);host.mkdir()
(host/'host.sh').write_bytes(wrapper);(host/'host.sh').chmod(0o755)
(host/'runtime-inventory.json').write_text(json.dumps(expected,indent=2)+'\n')
framework=host/shared;framework.mkdir(parents=True)
(framework/'.version').write_text(commit+'\n'+version+'\n')
(framework/'Microsoft.NETCore.App.runtimeconfig.json').write_text(json.dumps({'runtimeOptions':{'tfm':'net10.0'}},indent=2)+'\n')
identity='Microsoft.NETCore.App.Runtime.linux-arm64/'+version
target='.NETCoreApp,Version=v10.0/linux-arm64'
products={'runtime':{name:{} for name in sorted(manifest['managed'])},'native':{name:{} for name,path in sorted(manifest['nativePaths'].items()) if path.startswith(shared+'/')}}
deps={'runtimeTarget':{'name':target,'signature':''},'compilationOptions':{},'targets':{'.NETCoreApp,Version=v10.0':{},target:{identity:products}},'libraries':{identity:{'type':'package','serviceable':True,'sha512':''}}}
(framework/'Microsoft.NETCore.App.deps.json').write_text(json.dumps(deps,indent=2)+'\n')
for name in ['LICENSE.TXT','THIRD-PARTY-NOTICES.TXT']:
    if (w/'upstream'/name).is_file():shutil.copyfile(w/'upstream'/name,framework/name)
paths.update({str(p.relative_to(host)):str(p.relative_to(host)) for p in host.rglob('*') if p.is_file()})
assert not any(p.suffix in ['.dll','.so'] or p.name=='dotnet' for p in host.rglob('*'))
(host/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_layout","msbuild_runtime")\nmsbuild_layout(name="tree",paths='+json.dumps(paths)+')\nmsbuild_runtime(name="host",layout=":tree",entry_point="host.sh",visibility=["//visibility:public"])\n')
manifest.update(sourceOnly=True,frameworkVersion=version,installed=[],excludedRuntimeComponents=excluded)
(w/'subset.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Source-only framework',version,'managed',len(manifest['managed']),'native',len(manifest['native']),'excluded',len(excluded),flush=True)
