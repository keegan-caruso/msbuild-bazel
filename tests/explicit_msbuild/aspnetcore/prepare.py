"""Experimental BUILD declarations for the evaluated ASP.NET Core graph.

This is benchmark setup, not production discovery. The bootstrap outputs are
captured inputs for initial qualification; generation is not yet a Bazel action.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

source, inventory, workspace, rules = map(lambda p: Path(p).resolve(), sys.argv[1:])
all_rows = {(r['project'],r['framework']): r for r in json.loads(inventory.read_text()) if r['framework']}
entries = set(json.loads((inventory.parent/'selection.json').read_text())['entries'])
pending = [key for key in all_rows if key[0] in entries]
selected = set()
while pending:
    key = pending.pop()
    if key in selected: continue
    selected.add(key)
    pending.extend((e['project'],e['framework']) for e in all_rows[key]['selectedEdges'])
rows = [all_rows[key] for key in sorted(selected)]
root = workspace / 'upstream'
shutil.copytree(source, root, ignore=shutil.ignore_patterns('.git', '.dotnet', 'bin', 'obj', 'artifacts', 'node_modules'))
archive_root = root / 'locked-packages'
archive_root.mkdir()
shutil.copyfile(Path(__file__).with_name('layout.targets'), root/'layout.targets')
# Preserve generated bootstrap inputs as explicit files during qualification.
for name in ['Directory.Build.props', 'Directory.Build.targets']:
    path = Path('artifacts/bin/GenerateFiles') / name
    (root / path).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / path, root / path)
header = ['load("@rules_msbuild//msbuild:toolchain.bzl", "msbuild_toolchain")',
          'load("@rules_msbuild//msbuild:defs.bzl", "msbuild_library", "msbuild_binary", "msbuild_nuget_package", "msbuild_nuget_dependencies", "msbuild_package_lock", "msbuild_items", "msbuild_tool", "msbuild_project_output")',
          'msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")',
          'toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")']
def call(rule, **args):
    return rule + '(' + ','.join(k+'='+(str(v) if isinstance(v,bool) else json.dumps(v)) for k,v in args.items()) + ')'
def label(project, framework):
    return Path(project).stem + '_' + framework
by = {(r['project'], r['framework']): r for r in rows}
assert len(by) == len(rows), 'Distinct global configurations need distinct labels'
def logical(row, value):
    p = Path(value.replace('\\', '/'))
    if not p.is_absolute():
        p = source / Path(row['project']).parent / p
    p = p.resolve()
    return p.relative_to(source).as_posix() if p.is_relative_to(source) else None
packages = {}; closures = {}; declarations = []; manifest = {}; blocked = {}; project_bindings = {}
for row in rows:
    name = label(row['project'], row['framework'])
    assets = json.loads(Path(row['assets']).read_text())
    target = assets['targets'][row['framework']]
    locked = {k.lower().split('/')[0]: (k,v) for k,v in target.items() if v['type'] == 'package'}
    framework_assets = assets['project']['frameworks'][row['framework']]
    for d in framework_assets.get('downloadDependencies', []):
        versions = set(v.strip() for v in d['version'].strip('[]').split(','))
        assert len(versions) == 1, d
        version = versions.pop()
        locked.setdefault(d['name'].lower(), (d['name']+'/'+version, {}))
    # SDK imports are not project PackageReferences but still locked build inputs.
    for path in row['imports']:
        for folder in assets['packageFolders']:
            if path.startswith(folder):
                parts = Path(path).relative_to(folder).parts
                package_id, version = parts[:2]
                locked.setdefault(package_id, (package_id+'/'+version, {}))
    def archive_label(key): return 'archive_'+key.replace('/','_').lower()
    for key, _ in locked.values():
        package_id, version = key.split('/')
        filename = package_id.lower()+'.'+version+'.nupkg'
        archive = next(Path(p)/package_id.lower()/version/filename for p in assets['packageFolders'] if (Path(p)/package_id.lower()/version/filename).exists())
        if not (archive_root/filename).exists(): shutil.copyfile(archive,archive_root/filename)
        data = archive.read_bytes(); sha = hashlib.sha256(data).hexdigest(); digest = base64.b64encode(hashlib.sha512(data).digest()).decode()
        manifest[key] = dict(sha256=sha, contentHash=digest)
        packages[archive_label(key)] = call('msbuild_nuget_package', name=archive_label(key), package_id=package_id,version=version,archive='locked-packages/'+filename,archive_sha256=sha,content_hash=digest)
    memo = {}
    def closure(package_id):
        if package_id in memo: return memo[package_id]
        key, record = locked[package_id]
        deps = sorted(closure(d.lower()) for d in record.get('dependencies',{}) if d.lower() in locked)
        tag = 'closure_'+hashlib.sha256(json.dumps([key,deps]).encode()).hexdigest()[:20]
        closures[tag] = call('msbuild_nuget_dependencies',name=tag,package=':'+archive_label(key),deps=deps)
        memo[package_id] = ':'+tag
        return ':'+tag
    declarations.append(call('msbuild_package_lock',name=name+'_lock',packages=[':'+archive_label(k) for k,_ in locked.values()]))
    deps=[]; analyzers=[]; tools=[]; outputs=[]; unsupported=[]
    for ref in row['references']:
        project=logical(row,ref['include'])
        candidates=[e for e in row['selectedEdges'] if e['project']==project and e['framework']]
        assert len(candidates)==1,(name,project,candidates)
        dep=':'+label(project,candidates[0]['framework'])
        if ref['metadata'].get('OutputItemType')=='Analyzer': analyzers.append(dep)
        elif ref['metadata'].get('ReferenceOutputAssembly','').lower()=='false':
            if ref['metadata'].get('OutputItemType','') in ('Content','None'):
                tag=name+'_output_'+str(len(outputs))
                declarations.append(call('msbuild_project_output',name=tag,assembly=dep,item_type=ref['metadata']['OutputItemType'],metadata={k:v for k,v in ref['metadata'].items() if k in ('CopyToOutputDirectory','CopyToPublishDirectory')}))
                outputs.append(':'+tag)
            elif ref['metadata'].get('OutputItemType',''): unsupported.append(ref)
            else:
                tool=name+'_tool_'+str(len(tools))
                declarations.append(call('msbuild_tool',name=tool,assembly=dep))
                tools.append(':'+tool)
        else: deps.append(dep)
    reference_packages=[p for p in row['bareReferences'] if p['include'].lower() in locked]
    pkg=[closure(p['include'].lower()) for p in row['packages']]
    bound=[closure(p['include'].lower()) for p in reference_packages]
    allpkg=sorted(set(pkg+bound))
    imports={p for value in row['imports'] if (p:=logical(row,value)) is not None and not ('artifacts/obj/' in p or '/obj/' in p or '/bin/' in p)}
    imports.update(['global.json','artifacts/bin/GenerateFiles/Directory.Build.props','artifacts/bin/GenerateFiles/Directory.Build.targets'])
    for parent in (source/row['project']).parents:
        if not parent.is_relative_to(source): break
        if (parent/'.editorconfig').exists(): imports.add((parent/'.editorconfig').relative_to(source).as_posix())
    sources=[p for item in row['compile'] if (p:=logical(row,item['include'])) is not None and '/obj/' not in p and '/bin/' not in p]
    items=[]
    for kind, values in row['items'].items():
        for i, item in enumerate(values):
            path=logical(row,item['include'])
            if path is None or not (root/path).is_file(): continue
            meta={k:v for k,v in item['metadata'].items() if k in ['Link','LogicalName','CopyToOutputDirectory','CopyToPublishDirectory','TargetPath','Culture','WithCulture','Generator','LastGenOutput','DependentUpon','GenerateSource','StronglyTypedClassName','StronglyTypedNamespace','Namespace','ClassName','ExcludeFromManifest','GenerateResourcesCodeAsConstants','ManifestResourceName','LinkBase'] and v}
            tag=name+'_'+kind+'_'+str(i)
            declarations.append(call('msbuild_items',name=tag,item_type=kind,srcs=[path],metadata=meta));items.append(':'+tag)
    attrs=dict(name=name,project=row['project'],target_framework=row['framework'],assembly_name=row['properties']['AssemblyName'],srcs=sources,items=items,use_apphost=row['properties']['UseAppHost'].lower()=='true',tools=tools,project_outputs=outputs,deps=deps+pkg,analyzers=analyzers+allpkg,build_deps=allpkg,reference_packages=bound,framework_assemblies=[p['include'] for p in row['bareReferences'] if p['include'].lower() not in locked and not Path(p['include']).is_absolute()],package_lock=':'+name+'_lock',package_private_assets={p['include']:p['metadata']['PrivateAssets'].lower() for p in row['packages']+reference_packages if p['metadata'].get('PrivateAssets')},framework_refs=[p['include'] for p in row['frameworks'] if p['metadata'].get('IsImplicitlyDefined','').lower()!='true'],msbuild_imports=sorted(imports),msbuild_properties={'RootNamespace':row['properties']['RootNamespace'],'WarningsNotAsErrors':'CS8629;IDE0031','RepositoryCommit':'7387de91234d3ef751fa50b3d1bfede4130213ff','SourceRevisionId':'7387de91234d3ef751fa50b3d1bfede4130213ff'},lang_version=row['properties']['LangVersion'] or 'default',nullable=row['properties']['Nullable'] or 'disable',allow_unsafe=row['properties']['AllowUnsafeBlocks'].lower()=='true',adapter_imports=['layout.targets'],directories=['upstream/artifacts/installers/Release','upstream/artifacts/VSSetup/Release'],linux_worker=True)
    if unsupported:
        blocked[name] = unsupported
        declarations.append(call('unsupported_project',name=name,reason='Unsupported project output role: '+json.dumps(unsupported)))
        continue
    kind = 'msbuild_binary' if row['properties']['OutputType']=='Exe' else 'msbuild_library'
    if os.environ.get('RULES_MSBUILD_SYNC_INPUTS_ONLY') == '1':
        project_bindings[name] = dict(rule=kind, attributes=attrs)
    else:
        declarations.append(call(kind, **attrs))
header.append('load(":qualification.bzl", "unsupported_project")')
(root/'qualification.bzl').write_text('def _unsupported(ctx):\n    fail(ctx.attr.reason)\nunsupported_project = rule(implementation=_unsupported, attrs={"reason":attr.string()})\n')
if project_bindings:
    (workspace/'project-bindings.json').write_text(json.dumps(project_bindings, indent=2) + '\n')
(workspace/'blocked.json').write_text(json.dumps(blocked,indent=2)+'\n')
(root/'BUILD.bazel').write_text('\n'.join(header+list(packages.values())+list(closures.values())+declarations)+ '\n'+call('filegroup',name='benchmark',srcs=[':'+label(r['project'],r['framework']) for r in rows])+'\n')
(workspace/'MODULE.bazel').write_text('module(name="aspnetcore_scale")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(rules))+')\nsdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")\nsdk(name="dotnet",path='+json.dumps(os.environ['RULES_MSBUILD_DOTNET_ROOT'])+',include_runtime_closure=False)\nregister_toolchains("//upstream:registered")\n')
(workspace/'package-lock.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Declared',len(rows),'framework nodes,',len(packages),'packages',flush=True)

(workspace/'all-targets.txt').write_text('\n'.join('//upstream:'+label(r['project'],r['framework']) for r in rows)+'\n')
