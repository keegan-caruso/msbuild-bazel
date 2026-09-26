"""Explicit BUILD declarations for pinned runtime managed qualification slices.

This is qualification setup, not production discovery. All selected managed tools
are built by Bazel. Only source and locked package archives are acquired during setup.
"""
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sys
import zipfile
import xml.etree.ElementTree as ET

from compiler_reuse import compiler_properties

source, inventory, workspace, rules = map(lambda p: Path(p).resolve(), sys.argv[1:])
sdk_version = json.loads((rules/'global.json').read_text())['sdk']['version']
framework_rows = [r for r in json.loads(inventory.read_text()) if r['framework']]
all_rows = {(r['project'],r['framework']): r for r in framework_rows}
assert len(all_rows) == len(framework_rows), 'Qualification labels require unique project/framework configurations'
# Build tools may target a newer framework than the assembly consuming them.
# Accept only the graph's unique configured producer for a non-compile edge;
# never choose an incompatible compile dependency by this fallback.
for row in framework_rows:
    for ref in row['references']:
        project=str((source/Path(row['project']).parent/ref['include'].replace('\\','/')).resolve().relative_to(source))
        edge=next((e for e in row['selectedEdges'] if e['project']==project),None)
        explicit=ref['metadata'].get('SetTargetFramework','')
        if edge is not None and explicit.startswith('TargetFramework=') and ';' not in explicit:
            # An authored override wins over nearest-framework reduction even
            # when both framework nodes exist elsewhere in the graph.
            requested=explicit.split('=',1)[1]
            assert requested in {e['framework'] for e in row['edges'] if e['project']==project},(project,requested)
            edge['framework']=requested
        if edge is not None and edge['framework'] is None and ref['metadata'].get('ReferenceOutputAssembly','').lower()=='false':
            frameworks={e['framework'] for e in row['edges'] if e['project']==project and e['framework']}
            explicit=ref['metadata'].get('SetTargetFramework','')
            if explicit.startswith('TargetFramework=') and ';' not in explicit:
                requested=explicit.split('=',1)[1]
                assert requested in frameworks,(project,requested,frameworks)
                edge['framework']=requested
            else:
                assert len(frameworks)==1,(project,frameworks)
                edge['framework']=frameworks.pop()
selection = json.loads((inventory.parent/'selection.json').read_text())
entries = {(entry,selection.get('framework','net10.0')) if isinstance(entry,str) else (entry['project'],entry['framework']) for entry in selection['entries']}
assert entries <= set(all_rows), entries - set(all_rows)
pending = list(entries)
selected = set()
while pending:
    key = pending.pop()
    if key in selected: continue
    selected.add(key)
    row=all_rows[key]
    direct={str((source/Path(row['project']).parent/r['include'].replace('\\','/')).resolve().relative_to(source)) for r in row['references']}
    pending.extend((e['project'],e['framework']) for e in row['selectedEdges'] if e['project'] in direct)
rows = [all_rows[key] for key in sorted(selected)]
workspace.mkdir(parents=True,exist_ok=True)
(workspace/'host-selection.json').write_text(json.dumps({k:selection.get(k,{}) for k in ['hostFrameworks','privateFrameworks']})+'\n')
root = workspace / 'upstream'
shutil.copytree(source, root, ignore=shutil.ignore_patterns('.git', '.dotnet', 'bin', 'obj', 'artifacts', 'node_modules'))
archive_root = root / 'locked-packages'
archive_root.mkdir()
shutil.copyfile(Path(__file__).with_name('layout.targets'), root/'layout.targets')
header = ['load("@rules_msbuild//msbuild:toolchain.bzl", "msbuild_toolchain")',
          'load("@rules_msbuild//msbuild:defs.bzl", "msbuild_library", "msbuild_binary", "msbuild_nuget_package", "msbuild_nuget_dependencies", "msbuild_package_lock", "msbuild_items", "msbuild_tool", "msbuild_project_output", "msbuild_assembly", "msbuild_file_binding", "msbuild_test", "msbuild_test_tool", "msbuild_layout", "msbuild_runtime")',
          'msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")',
          'toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")']
def call(rule, **args):
    return rule + '(' + ','.join(k+'='+(str(v) if isinstance(v,bool) else json.dumps(v)) for k,v in args.items()) + ')'
def label(project, framework):
    return project.removesuffix('.csproj').replace('/', '_') + '_' + framework
by = {(r['project'], r['framework']): r for r in rows}
assert len(by) == len(rows), 'Distinct global configurations need distinct labels'
def logical(row, value):
    p = Path(value.replace('\\', '/'))
    if not p.is_absolute():
        p = source / Path(row['project']).parent / p
    p = p.resolve()
    return p.relative_to(source).as_posix() if p.is_relative_to(source) else None
packages = {}; closures = {}; declarations = []; manifest = {}; blocked = {}; project_bindings = {}
paired = {}; contract_layouts = {}; forwarding_contracts = set()
for row in rows:
    if '/ref/' in row['project']:
        name=label(row['project'],row['framework'])
        declarations.append(call('filegroup',name=name+'_reference_output',srcs=[':'+name],output_group='reference'))
def contract_closure(key):
    found=set();pending=[key]
    while pending:
        current=pending.pop()
        if current in found: continue
        found.add(current)
        row=by[current]
        for ref in row['references']:
            if ref['metadata'].get('ReferenceOutputAssembly','').lower()=='false': continue
            project=logical(row,ref['include'])
            edge=next(e for e in row['selectedEdges'] if e['project']==project)
            pending.append((project,edge['framework']))
    assert all('/ref/' in project for project,_ in found),found
    return sorted(found)
for row in rows:
    for ref in row['references']:
        if ref['metadata'].get('OutputItemType') != 'ResolvedMatchingContract': continue
        project = logical(row, ref['include'])
        edge = next(e for e in row['selectedEdges'] if e['project'] == project)
        implementation = label(row['project'], row['framework'])
        paired[implementation] = implementation + '_paired'
        contract_row=by[(project,edge['framework'])]
        if any(re.search(r'\[assembly\s*:\s*(?:global::)?(?:System\.Runtime\.CompilerServices\.)?TypeForwardedTo(?:Attribute)?\s*\(', (source/path).read_text()) for item in contract_row['compile'] if (path:=logical(contract_row,item['include'])) is not None and (source/path).is_file()):
            forwarding_contracts.add(implementation)
        # Upstream shims explicitly disable APICompat and allow their reference
        # projects to use source/stub dependencies (shims/Directory.Build.props).
        if not row['project'].startswith('src/libraries/shims/'):
            contract_layouts[implementation]=implementation+'_contract_layout'
            paths={':'+label(p,f)+'_reference_output':by[(p,f)]['properties']['AssemblyName']+'.dll' for p,f in contract_closure((project,edge['framework']))}
            declarations.append(call('msbuild_layout',name=contract_layouts[implementation],paths=paths))
        declarations.append(call('msbuild_assembly', name=paired[implementation], contract=':'+label(project,edge['framework']), implementation=':'+implementation))
        declarations.append(call('msbuild_assembly', name=paired[implementation]+'_implementation_reference', contract=':'+label(project,edge['framework']), implementation=':'+implementation,use_implementation_reference=True))
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
    deps=[]; analyzers=[]; tools=[]; outputs=[]; unsupported=[]; bindings=[]; source_outputs=[]
    corelib_project='src/coreclr/System.Private.CoreLib/System.Private.CoreLib.csproj'
    # Runtime's HandleReferenceAssemblyAttributeForProjectReferences selects
    # implementation facades when compiling against CoreLib. Its subsequent
    # ReplaceCoreLibSrcWithRefAssemblyForCompilation keeps CoreLib itself a ref.
    implementation_references=any(logical(row,r['include'])==corelib_project for r in row['references'])
    for ref in row['references']:
        project=logical(row,ref['include'])
        candidates=[e for e in row['selectedEdges'] if e['project']==project and e['framework']]
        assert len(candidates)==1,(name,project,candidates)
        dep=':'+label(project,candidates[0]['framework'])
        if ref['metadata'].get('OutputItemType')=='Analyzer': analyzers.append(dep)
        elif ref['metadata'].get('ReferenceOutputAssembly','').lower()=='false':
            if ref['metadata'].get('OutputItemType','') in ('Content','None','ResolvedMatchingContract'):
                tag=name+'_output_'+str(len(outputs))
                declarations.append(call('msbuild_project_output',name=tag,assembly=dep,item_type=ref['metadata']['OutputItemType'],artifact='reference' if '/ref/' in project else 'implementation',metadata={k:v for k,v in ref['metadata'].items() if k in ('CopyToOutputDirectory','CopyToPublishDirectory')}))
                outputs.append(':'+tag)
            elif ref['metadata'].get('OutputItemType')=='_contractSourceFilesGroup' and ref['metadata'].get('Targets')=='SourceFilesProjectOutputGroup':
                # GenFacades consumes only relative C# contract sources from
                # this SDK output group. Keep them explicit file edges; scalar
                # target exports and DLL outputs cannot represent this role.
                contract=by[(project,candidates[0]['framework'])]
                inputs=[item for item in contract['compile'] if not Path(item['include'].replace('\\','/')).is_absolute() and item['include'].endswith('.cs')]
                assert inputs,(project,ref)
                for item in inputs:
                    path=logical(contract,item['include']);assert path and (root/path).is_file(),item
                    tag=name+'_contract_source_'+str(len(source_outputs))
                    declarations.append(call('msbuild_items',name=tag,item_type='_contractSourceFilesGroup',srcs=[path],metadata={'OriginalItemSpec':item['include']}))
                    source_outputs.append(':'+tag)
            elif ref['metadata'].get('OutputItemType',''): unsupported.append(ref)
            else:
                tool=name+'_tool_'+str(len(tools))
                declarations.append(call('msbuild_tool',name=tool,assembly=dep,layout_prefix='net' if project.endswith('/ILLink.Tasks/ILLink.Tasks.csproj') else ''))
                tools.append(':'+tool)
                if project.endswith('/ILLink.Tasks/ILLink.Tasks.csproj'):
                    binding=tool+'_location'
                    declarations.append(call('msbuild_file_binding',name=binding,tool=':'+tool,property_name='ILLinkTasksAssembly'))
                    bindings.append(':'+binding)
        else:
            use_implementation=ref['metadata'].get('SkipUseReferenceAssembly','').lower() == 'true' or (implementation_references and row['properties'].get('CompileUsingReferenceAssemblies','').lower()!='true' and project != corelib_project)
            platform_implementation='-' in candidates[0]['framework'] and candidates[0]['framework']!=row['framework']
            if use_implementation and platform_implementation and dep[1:] in paired:
                deps.append(':'+paired[dep[1:]]+'_implementation_reference')
            else:deps.append(dep if use_implementation else ':'+paired.get(dep[1:],dep[1:]))
    package_reference_paths = {}
    for reference in row['bareReferences']:
        if reference['metadata'].get('NuGetPackageId'): continue
        for package_root in assets['packageFolders']:
            path = Path(reference['include'])
            if path.is_relative_to(package_root):
                package_id, version, *parts = path.relative_to(package_root).parts
                assert package_id in locked and locked[package_id][0].split('/')[1] == version
                package_reference_paths.setdefault(package_id, []).append('/'.join(parts))
    reference_packages=[p for p in row['bareReferences'] if p['include'].lower() in locked]
    pkg=[closure(p['include'].lower()) for p in row['packages']]
    bound=[closure(p['include'].lower()) for p in reference_packages]
    allpkg=sorted(set(pkg+bound))
    imports={p for value in row['imports'] if (p:=logical(row,value)) is not None and not ('artifacts/obj/' in p or '/obj/' in p or '/bin/' in p)}
    imports.update(logical(row, ref['include']) for ref in row['references'])
    # ASN generation reads a stylesheet beside its imported upstream target.
    for path in tuple(imports):
        if path and path.endswith('/AsnXml.targets'):
            imports.add(str(Path(path).with_name('asn.xslt')))
    suppression = row['properties'].get('CompatibilitySuppressionFilePath') or 'CompatibilitySuppressions.xml'
    suppression = logical(row, suppression)
    if suppression and (root/suppression).is_file(): imports.add(suppression)
    imports.update(['eng/testing/.runsettings', 'eng/DefaultGenApiDocIds.txt', 'eng/ApiCompatExcludeAttributes.txt', 'eng/ILLink.Substitutions.Resources.template', 'global.json', 'src/libraries/Microsoft.NETCore.Platforms/src/PortableRuntimeIdentifierGraph.json', 'src/libraries/Microsoft.NETCore.Platforms/src/runtime.json'])
    for parent in (source/row['project']).parents:
        if not parent.is_relative_to(source): break
        if (parent/'.editorconfig').exists(): imports.add((parent/'.editorconfig').relative_to(source).as_posix())
    if row['project'] == 'src/coreclr/System.Private.CoreLib/System.Private.CoreLib.csproj':
        imports.update(['src/coreclr/vm/namespace.h', 'src/coreclr/vm/corelib.h', 'src/coreclr/inc/cortypeinfo.h', 'src/coreclr/vm/rexcep.h'])
    # Property-valued task inputs are not evaluation-time items. Omitting
    # them changes Exists() and can alter generation or trimming.
    for property_name in ['ApiExclusionListPath','ILLinkDescriptorsXml','ILLinkSubstitutionsXml','ILLinkLinkAttributesXml','ILLinkSubstitutionsLibraryBuildXml']:
        value=row['properties'].get(property_name)
        path=logical(row,value) if value else None
        if path and (root/path).is_file(): imports.add(path)
    sources=[p for item in row['compile'] if (p:=logical(row,item['include'])) is not None and '/obj/' not in p and '/bin/' not in p]
    items=list(source_outputs)
    for kind, values in row['items'].items():
        for i, item in enumerate(values):
            path=logical(row,item['include'])
            if path is None or not (root/path).is_file(): continue
            if kind not in ['EmbeddedResource','Content','None','AdditionalFiles','GlobalAnalyzerConfigFiles','EditorConfigFiles']:
                # These upstream task inputs may also contain generated items.
                # Stage the source files without replacing the evaluated list.
                imports.add(path)
                continue
            if kind == 'EmbeddedResource':
                imports.update(p.relative_to(root).as_posix() for p in (root/path).parent.glob('xlf/*.xlf'))
            meta={k:v for k,v in item['metadata'].items() if k in ['Link','LogicalName','CopyToOutputDirectory','CopyToPublishDirectory','TargetPath','Culture','WithCulture','Generator','LastGenOutput','DependentUpon','GenerateSource','StronglyTypedClassName','StronglyTypedNamespace','Namespace','ClassName','ExcludeFromManifest','GenerateResourcesCodeAsConstants','ManifestResourceName','LinkBase'] and v}
            tag=name+'_'+kind+'_'+str(i)
            declarations.append(call('msbuild_items',name=tag,item_type=kind,srcs=[path],metadata=meta));items.append(':'+tag)
    attrs=dict(name=name,adapter_imports=["layout.targets"],package_reference_paths=package_reference_paths,project=row['project'],target_framework=row['framework'],assembly_name=row['properties']['AssemblyName'],srcs=sources,items=items,use_apphost=row['properties']['UseAppHost'].lower()=='true',tools=tools,bindings=bindings,project_outputs=outputs,deps=sorted(set(deps+pkg)),analyzers=analyzers+allpkg,build_deps=allpkg,reference_packages=bound,framework_assemblies=[p['include'] for p in row['bareReferences'] if p['include'].lower() not in locked and not Path(p['include']).is_absolute()],package_lock=':'+name+'_lock',package_private_assets={p['include']:p['metadata']['PrivateAssets'].lower() for p in row['packages']+reference_packages if p['metadata'].get('PrivateAssets')},framework_refs=[p['include'] for p in row['frameworks'] if p['metadata'].get('IsImplicitlyDefined','').lower()!='true'],msbuild_imports=sorted(imports),output_mode='reference' if '/ref/' in row['project'] else 'implementation',configuration='Release',msbuild_properties={**compiler_properties(locked,manifest,sdk_version),'RootNamespace':row['properties']['RootNamespace'],'TargetArchitecture':'arm64','TargetOS':'linux','UseLocalTargetingRuntimePack':'false','RepositoryCommit':'60629d14374c56f1cb51819049ad1fa529307f8d','SourceRevisionId':'60629d14374c56f1cb51819049ad1fa529307f8d'},lang_version=row['properties']['LangVersion'] or 'default',nullable=row['properties']['Nullable'] or 'disable',allow_unsafe=row['properties']['AllowUnsafeBlocks'].lower()=='true',linux_worker=True)
    if implementation_references:
        # Upstream shared framework references are private and RAR dependency
        # discovery is disabled. CoreLib consumers author their direct inputs.
        attrs['transitive_compile_references']=False
    if name in contract_layouts:
        attrs['layout_bindings']={':'+contract_layouts[name]:'MicrosoftNetCoreAppRefPackRefDir'}
        # Forwarded types must resolve against the same implementation inputs on
        # both sides, as in upstream's default APICompat policy.
        if name in forwarding_contracts or implementation_references or row['project']==corelib_project:
            attrs['msbuild_properties']['ApiCompatUseImplementationReferencesForContract']='true' if name in forwarding_contracts else 'false'
        if implementation_references and row['properties']['TargetFrameworks']:
            attrs['msbuild_properties']['RunApiCompatValidateAssembliesInInnerBuild']='true'
    if unsupported:
        blocked[name] = unsupported
        declarations.append(call('unsupported_project',name=name,reason='Unsupported project output role: '+json.dumps(unsupported)))
        continue
    if row['properties']['IsTestProject'].lower() == 'true':
        adapter_key=locked['xunit.runner.visualstudio'][0]
        archive=archive_root/(adapter_key.replace('/','.').lower()+'.nupkg')
        with zipfile.ZipFile(archive) as z:
            adapter_paths=[str(Path(p).parent) for p in z.namelist() if p.endswith('xunit.runner.visualstudio.testadapter.dll') and '/net4' not in p]
        assert len(adapter_paths)==1,adapter_paths
        declarations.append(call('msbuild_test_tool',name=name+'_adapter',package=':'+archive_label(adapter_key),path=adapter_paths[0]))
        attrs.update(test_protocol='vstest',test_settings_output='.runsettings',test_output_type='exe' if row['properties']['OutputType']=='Exe' else 'library',test_runner=':test_runner',test_adapters=[':'+name+'_adapter'],runtime_host='//runtime:host',size='medium')
        if row['project'] in selection.get('filters',{}):
            settings=ET.parse(Path(row['properties']['OutputPath'])/'.runsettings')
            config=settings.getroot().find('RunConfiguration');assert config is not None
            element=config.find('TestCaseFilter')
            if element is None:element=ET.SubElement(config,'TestCaseFilter')
            positive=selection['filters'][row['project']]
            element.text=('('+element.text+')&' if element.text else '')+'('+positive+')'
            path=root/'qualification-settings'/(name+'.runsettings');path.parent.mkdir(exist_ok=True)
            settings.write(path,encoding='utf-8',xml_declaration=True)
            attrs.pop('test_settings_output')
            attrs['test_settings']=path.relative_to(root).as_posix()
        kind = 'msbuild_test'
    else:
        kind = 'msbuild_binary' if row['properties']['OutputType']=='Exe' else 'msbuild_library'
    if os.environ.get('RULES_MSBUILD_SYNC_INPUTS_ONLY') == '1':
        project_bindings[name] = dict(rule=kind, attributes=attrs)
    else:
        declarations.append(call(kind, **attrs))
if any(r['properties']['IsTestProject'].lower()=='true' for r in rows):
    runner=Path(os.environ['RULES_MSBUILD_VSTEST_ARCHIVE'])
    data=runner.read_bytes()
    assert hashlib.sha256(data).hexdigest()=="3aabba2641a165f8274fbad94ed1c4e2a004877d37b2ddfab89962487f3dceab", "Unpinned VSTest archive"
    manifest['Microsoft.TestPlatform.CLI/17.14.1']=dict(sha256=hashlib.sha256(data).hexdigest(),contentHash=base64.b64encode(hashlib.sha512(data).digest()).decode())
    shutil.copyfile(runner,archive_root/'test-runner.nupkg')
    header.append(call('msbuild_nuget_package',name='test_runner_archive',package_id='Microsoft.TestPlatform.CLI',version='17.14.1',archive='locked-packages/test-runner.nupkg',archive_sha256=hashlib.sha256(data).hexdigest(),content_hash=base64.b64encode(hashlib.sha512(data).digest()).decode()))
    header.append(call('msbuild_test_tool',name='test_runner',package=':test_runner_archive',path='contentFiles/any/net9.0/vstest.console.dll'))
    host=workspace/'runtime';host.mkdir()
    sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
    for relative in ['dotnet','host','shared/Microsoft.NETCore.App']:
        source_path=sdk/relative;dest=host/relative;dest.parent.mkdir(parents=True,exist_ok=True)
        if source_path.is_dir():shutil.copytree(source_path,dest,copy_function=os.link)
        else:os.link(source_path,dest)
    paths={str(p.relative_to(host)):str(p.relative_to(host)) for p in host.rglob('*') if p.is_file()}
    (host/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_layout","msbuild_runtime")\n'+call('msbuild_layout',name='tree',paths=paths)+'\n'+call('msbuild_runtime',name='host',layout=':tree',entry_point='dotnet',visibility=['//visibility:public'])+'\n')
header.append('load(":qualification.bzl", "unsupported_project")')
(root/'qualification.bzl').write_text('def _unsupported(ctx):\n    fail(ctx.attr.reason)\nunsupported_project = rule(implementation=_unsupported, attrs={"reason":attr.string()})\n')
(workspace/'blocked.json').write_text(json.dumps(blocked,indent=2)+'\n')
if project_bindings:
    (workspace/'project-bindings.json').write_text(json.dumps(project_bindings, indent=2)+'\n')
(root/'BUILD.bazel').write_text('\n'.join(header+list(packages.values())+list(closures.values())+declarations)+ '\n'+call('filegroup',name='benchmark',testonly=any(r['properties']['IsTestProject'].lower()=='true' for r in rows),srcs=[':'+label(r['project'],r['framework']) for r in rows])+'\n')
(workspace/'MODULE.bazel').write_text('module(name="runtime_reference")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(rules))+')\nsdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")\nsdk(name="dotnet",path='+json.dumps(os.environ['RULES_MSBUILD_DOTNET_ROOT'])+',include_runtime_closure=False)\nregister_toolchains("//upstream:registered")\n')
(workspace/'package-lock.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Declared',len(rows),'framework nodes,',len(packages),'packages',flush=True)

(workspace/'all-targets.txt').write_text('\n'.join('//upstream:'+label(r['project'],r['framework']) for r in rows)+'\n')
