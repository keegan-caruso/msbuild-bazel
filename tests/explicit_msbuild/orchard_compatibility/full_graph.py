"""Prepare explicit Orchard BUILD declarations outside benchmark timing.

Requires FullGraphProbe inventory and raw restore in a disposable Orchard copy.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

root=Path(sys.argv[1]).resolve();inventory=Path(sys.argv[2]);rules=Path(sys.argv[3]).resolve()
sdk=os.environ['RULES_MSBUILD_DOTNET_ROOT'];rows=json.loads(inventory.read_text());by={r['project']:r for r in rows}
packages=root/'locked-packages';packages.mkdir(exist_ok=True)
header=['load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")','load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_binary","msbuild_nuget_package","msbuild_items","msbuild_target_items","msbuild_nuget_dependencies","msbuild_package_lock")', 'msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")','toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")']
def call(rule,**args):return rule+'('+','.join(k+'='+str(v) if isinstance(v,bool) else k+'='+json.dumps(v) for k,v in args.items())+')'
def label(project):return Path(project).stem
package_rules={};project_packages={};locks={};closure_rules={}
for row in rows:
 assets=json.loads((root/Path(row['project']).parent/'obj/project.assets.json').read_text())
 target=assets['targets'].get(row['framework'],next(iter(assets['targets'].values())))
 locked={key.split('/')[0].lower():(key,value) for key,value in target.items() if value.get('type')=='package'}
 def archive_label(key):return 'archive_'+key.replace('/','_').lower()
 for key,record in locked.values():
  name,version=key.split('/');archive_name=f'{name.lower()}.{version}.nupkg';archive=Path('/tmp/nuget')/name.lower()/version/archive_name
  if not (packages/archive_name).exists():shutil.copyfile(archive,packages/archive_name)
  if archive_label(key) not in package_rules:
   package_rules[archive_label(key)]=call('msbuild_nuget_package',name=archive_label(key),package_id=name,version=version,archive='locked-packages/'+archive_name,archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),content_hash=assets['libraries'][key]['sha512'])
 memo={}
 def closure(name):
  if name in memo:return memo[name]
  key,record=locked[name]
  deps=sorted(closure(d.lower()) for d in record.get('dependencies',{}) if d.lower() in locked)
  tag='closure_'+hashlib.sha256(json.dumps([key,deps]).encode()).hexdigest()[:20]
  closure_rules[tag]=call('msbuild_nuget_dependencies',name=tag,package=':'+archive_label(key),deps=[':'+d for d in deps]);memo[name]=tag;return tag
 project_packages[row['project']]={name:':'+closure(name) for name in locked}
 locks[row['project']]=call('msbuild_package_lock',name=label(row['project'])+'_lock',packages=[':'+archive_label(key) for key,_ in locked.values()])
header+=list(package_rules.values())+list(closure_rules.values())+list(locks.values())
metadata_names=['Link','LogicalName','CopyToOutputDirectory','CopyToPublishDirectory','TargetPath','Culture','WithCulture','Generator','LastGenOutput','DependentUpon']
def logical(row,include):
 p=Path(include.replace('\\','/'))
 if not p.is_absolute():p=root/Path(row['project']).parent/p
 return p.resolve().relative_to(root).as_posix()
def module_closure(project):
 found=set();pending=[project]
 while pending:
  current=by[pending.pop()]
  for ref in current['references']:
   if ref['metadata'].get('OutputItemType')=='Analyzer':continue
   child=logical(current,ref['include'])
   if child not in found:found.add(child);pending.append(child)
 return [':'+label(p) for p in sorted(found) if by[p]['module']]
for row in rows:
 name=label(row['project']);deps=[];analyzers=[]
 for ref in row['references']:
  p=logical(row,ref['include']);(analyzers if ref['metadata'].get('OutputItemType')=='Analyzer' else deps).append(':'+label(p))
 pkg=[project_packages[row['project']][p['include'].lower()] for p in row['packages']]
 items=[];imports=[p for p in row['imports'] if not {'bin','obj'}.intersection(Path(p).parts)]
 for parent in (root/row['project']).parents:
  if not parent.is_relative_to(root):break
  if (parent/'.editorconfig').exists():imports.append((parent/'.editorconfig').relative_to(root).as_posix())
 for kind,values in dict(row['items'],AdditionalFiles=row['additional']).items():
  if kind=='Folder':continue
  for i,item in enumerate(values):
   path=logical(row,item['include'])
   if {'bin','obj'}.intersection(Path(path).parts) or not (root/path).is_file():continue
   meta={k:v for k,v in item['metadata'].items() if k in metadata_names and v}
   target=f'{name}_{kind}_{i}';header.append(call('msbuild_items',name=target,item_type=kind,srcs=[path],metadata=meta));items.append(':'+target)
 modules=module_closure(row['project'])
 if modules and any(p.endswith('/OrchardCore.Application.Targets.targets') for p in imports):
  target=name+'_module_names';header.append(call('msbuild_target_items',name=target,deps=modules,target='GetModuleProjectName',item_type='ModuleProjectNames',before_targets=['ResolveModuleProjectReferences']));items.append(':'+target)
 attrs=dict(name=name,directories=sorted(set(logical(row,f["include"]) for f in row["items"]["Folder"])),package_lock=':'+name+'_lock',project=row['project'],assembly_name=row['properties']['AssemblyName'],target_framework=row['framework'],srcs=[logical(row,s['include']) for s in row['compile']],items=items,deps=deps+pkg,analyzers=analyzers+pkg,build_deps=pkg,package_private_assets={p['include']:p['metadata']['PrivateAssets'].lower() for p in row['packages'] if p['metadata'].get('PrivateAssets')},framework_refs=[p['include'] for p in row['frameworks'] if p['metadata'].get('IsImplicitlyDefined','').lower()!='true'],msbuild_imports=sorted(set(imports)),lang_version=row['properties']['LangVersion'] or 'default',nullable=row['properties']['Nullable'] or 'disable',linux_worker=True,profile_build=True)
 if row['module']:attrs['export_targets']={'GetModuleProjectName':[]}
 header.append(call('msbuild_binary' if row==rows[0] else 'msbuild_library',**attrs))
(root/'BUILD.bazel').write_text('\n'.join(header)+'\n')
(root/'MODULE.bazel').write_text('module(name="orchard_explicit")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(rules))+')\nsdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")\nsdk(name="dotnet",path='+json.dumps(sdk)+',include_runtime_closure=False)\nregister_toolchains("//:registered")\n')
print(json.dumps(dict(projects=len(rows),packageTargets=len(package_rules),itemTargets=len(header)-len(rows)-len(package_rules)-4)))
