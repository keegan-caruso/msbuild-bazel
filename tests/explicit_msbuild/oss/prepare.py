"""Disposable explicit BUILD fixture from a pinned, evaluated OSS configuration.

This is test scaffolding, not a production discovery/build entry point. Restore,
SDK pack acquisition and evaluation are setup costs, recorded outside build timing.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

folder=Path(sys.argv[1]).resolve(); rules=Path(sys.argv[2]).resolve()
source=folder/'source'; workspace=folder/'bazel'; config=json.loads((folder/'config.json').read_text()); root=workspace/config.get('sourceSubdir','')
rows=json.loads((folder/'inventory.json').read_text()); by={r['id']:r for r in rows}
assert len(by)==len(rows), 'Duplicate configured inventory node'
by_project={}
for row in rows: by_project.setdefault(row['project'],[]).append(row['id'])
shutil.copytree(source,root,ignore=shutil.ignore_patterns('bin','obj','.git','artifacts'),dirs_exist_ok=False)
packages=root/'locked-packages'; packages.mkdir()
header=['load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")','load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_binary","msbuild_nuget_package","msbuild_items","msbuild_nuget_dependencies","msbuild_package_lock","msbuild_tool","msbuild_file_binding")', 'msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")','toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")']
def call(rule,**args):
 def encode(v):return str(v) if isinstance(v,bool) else json.dumps(v)
 return rule+'('+','.join(k+'='+encode(v) for k,v in args.items())+')'
labels={}
stems={}
for row in rows: stems.setdefault(Path(row['project']).stem,[]).append(row['id'])
for row in rows:
 stem=Path(row['project']).stem
 labels[row['id']]=stem if len(stems[stem])==1 else stem+'_'+row['framework'].replace('.','_')+'_'+row['id'][:12]
assert len(set(labels.values()))==len(rows), 'Configured label collision'
def label(node): return labels[node]
def producer(row, project):
 if project in by: return project
 candidates=[ref['node'] for ref in row['references'] if by[ref['node']]['project']==project]
 if not candidates: candidates=by_project.get(project,[])
 assert len(set(candidates))==1, ('Tool binding requires a configured node ID',row['id'],project,candidates)
 return candidates[0]
def logical(row,include):
 p=Path(include.replace('\\','/'))
 if not p.is_absolute():p=source/Path(row['project']).parent/p
 p=p.resolve()
 return p.relative_to(source).as_posix() if p.is_relative_to(source) else None
package_rules={}; package_manifest={}; project_packages={}; locks={}; closure_rules={}
for row in rows:
 assets=json.loads(Path(row['assets']).read_text()); target=assets['targets'][row['framework']]
 locked={key.split('/')[0].lower():(key,value) for key,value in target.items() if value.get('type')=='package'}
 # Restore-only downloads (API baselines, reference packs) are still explicit
 # archive inputs, even though they are not compile-visible package references.
 for download in assets['project']['frameworks'][row['framework']].get('downloadDependencies',[]):
  name=download['name'];bounds=[v.strip() for v in download['version'].strip('[]').split(',')]
  assert download['version'].startswith('[') and download['version'].endswith(']') and len(set(bounds))==1,download
  version=bounds[0]
  key=name+'/'+version
  if name.lower() not in locked:
   locked[name.lower()]=(key,{'type':'package'})
 def archive_label(key):return 'archive_'+key.replace('/','_').lower()
 for key,record in locked.values():
  name,version=key.split('/');archive_name=f'{name.lower()}.{version}.nupkg'
  archive=next(Path(p)/name.lower()/version/archive_name for p in assets['packageFolders'] if (Path(p)/name.lower()/version/archive_name).exists())
  if not (packages/archive_name).exists():shutil.copyfile(archive,packages/archive_name)
  package_manifest[key]=dict(sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),contentHash=base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode())
  package_rules[archive_label(key)]=call('msbuild_nuget_package',name=archive_label(key),package_id=name,version=version,archive='locked-packages/'+archive_name,archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),content_hash=base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode())
 memo={}
 def closure(name):
  if name in memo:return memo[name]
  key,record=locked[name];deps=sorted(closure(d.lower()) for d in record.get('dependencies',{}) if d.lower() in locked)
  tag='closure_'+hashlib.sha256(json.dumps([key,deps]).encode()).hexdigest()[:20]
  closure_rules[tag]=call('msbuild_nuget_dependencies',name=tag,package=':'+archive_label(key),deps=[':'+d for d in deps]);memo[name]=tag;return tag
 project_packages[row['id']]={name:':'+closure(name) for name in locked}
 locks[row['id']]=call('msbuild_package_lock',name=label(row['id'])+'_lock',packages=[':'+archive_label(key) for key,_ in locked.values()])
header+=list(package_rules.values())+list(closure_rules.values())+list(locks.values())
metadata_names=['Link','LogicalName','CopyToOutputDirectory','CopyToPublishDirectory','TargetPath','Culture','WithCulture','Generator','LastGenOutput','DependentUpon']
tool_projects={ref['node'] for row in rows for ref in row['references'] if ref['metadata'].get('ReferenceOutputAssembly','').lower()=='false' and ref['metadata'].get('OutputItemType','')!='Analyzer'}
for row in rows:
 for project in config.get('toolBindings',{}).get(row['id'],config.get('toolBindings',{}).get(row['project'],{})).values(): tool_projects.add(producer(row,project))
for project in sorted(tool_projects):
 assert project in by,project
 header.append(call('msbuild_tool',name=label(project)+'_tool',assembly=':'+label(project)))
for row in rows:
 name=label(row['id']);deps=[];implementation=[];analyzers=[];tools=[];bindings=[]
 for ref in row['references']:
  p=ref['node']; assert p in by,(row['project'],ref)
  if ref['metadata'].get('OutputItemType')=='Analyzer':analyzers.append(':'+label(p))
  elif ref['metadata'].get('ReferenceOutputAssembly','').lower()=='false':tools.append(':'+label(p)+'_tool')
  elif ref['metadata'].get('PrivateAssets','').lower()=='all':implementation.append(':'+label(p))
  else:deps.append(':'+label(p))
 for property_name,project in config.get('toolBindings',{}).get(row['id'],config.get('toolBindings',{}).get(row['project'],{})).items():
  tool=':'+label(producer(row,project))+'_tool';tools.append(tool);binding=name+'_'+property_name
  header.append(call('msbuild_file_binding',name=binding,tool=tool,property_name=property_name));bindings.append(':'+binding)
 pkg=[project_packages[row['id']][p['include'].lower()] for p in row['packages']]
 items=[];imports={p for p in row['imports'] if not {'bin','obj','artifacts'}.intersection(Path(p).parts)}
 for parent in (source/row['project']).parents:
  if not parent.is_relative_to(source):break
  if (parent/'.editorconfig').exists():imports.add((parent/'.editorconfig').relative_to(source).as_posix())
 key=row['properties']['AssemblyOriginatorKeyFile']
 if key:
  key=logical(row,key);assert key is not None;imports.add(key)
 for kind,values in row['items'].items():
  for i,item in enumerate(values):
   path=logical(row,item['include'])
   if path is None or {'bin','obj','artifacts'}.intersection(Path(path).parts) or not (root/path).is_file():continue
   meta={k:v for k,v in item['metadata'].items() if k in metadata_names and v}
   target=f'{name}_{kind}_{i}';header.append(call('msbuild_items',name=target,item_type=kind,srcs=[path],metadata=meta));items.append(':'+target)
 # Raw controls use these same configuration values. Reserved runner properties
 # already have equivalent fixed values and cannot be passed through the API.
 props={k:v for k,v in row['globalProperties'].items() if k.lower() not in ('debugtype','producereferenceassembly','nugetaudit','configuration','targetframework')}
 props['RootNamespace']=row['properties']['RootNamespace']
 sources=[p for item in row['compile'] if (p:=logical(row,item['include'])) is not None and not {'bin','obj','artifacts'}.intersection(Path(p).parts)]
 attrs=dict(name=name,package_lock=':'+name+'_lock',project=row['project'],assembly_name=row['properties']['AssemblyName'],target_framework=row['framework'],configuration=next((v for k,v in row['globalProperties'].items() if k.lower()=='configuration'),'Release'),srcs=sources,items=items,tools=sorted(set(tools)),bindings=bindings,deps=deps+pkg,implementation_deps=implementation,analyzers=analyzers+pkg,build_deps=pkg,package_private_assets={p['include']:p['metadata']['PrivateAssets'].lower() for p in row['packages'] if p['metadata'].get('PrivateAssets')},framework_refs=[p['include'] for p in row['frameworks'] if p['metadata'].get('IsImplicitlyDefined','').lower()!='true'],msbuild_imports=sorted(imports),msbuild_properties=props,lang_version=row['properties']['LangVersion'] or 'default',nullable=row['properties']['Nullable'] or 'disable',allow_unsafe=row['properties']['AllowUnsafeBlocks'].lower()=='true',linux_worker=True)
 header.append(call('msbuild_binary' if row['properties']['OutputType']=='Exe' else 'msbuild_library',**attrs))
header.append('filegroup(name="benchmark",srcs='+json.dumps([':'+label(row['id']) for row in rows if row['entry']])+')')
(root/'BUILD.bazel').write_text('\n'.join(header)+'\n')
(workspace/'MODULE.bazel').write_text('module(name="oss_explicit")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(rules))+')\nsdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")\nsdk(name="dotnet",path='+json.dumps(os.environ['RULES_MSBUILD_DOTNET_ROOT'])+',include_runtime_closure=False)\nregister_toolchains("//'+config.get('sourceSubdir','')+':registered")\n')
summary=dict(projects=len(rows),packageTargets=len(package_rules),sourceFiles=sum(len(r['compile']) for r in rows),entries=config['entries'])
(folder/'package-lock.json').write_text(json.dumps(package_manifest,indent=2)+'\n')
(folder/'labels.json').write_text(json.dumps(labels,indent=2)+'\n')
(folder/'declarations.json').write_text(json.dumps(summary,indent=2));print(summary)
