"""Generate the selected runtime graph with explicit tool and package bindings.

Inputs: workspace from runtime/prepare.py, raw graph inventory, evaluation-only
sync inventory, target OS. This changes authored fixture setup, never the output
of msbuild_sync. Native runtime remains the pinned installed host in this slice.
"""
import ast
import json
import os
from pathlib import Path
import shutil
import sys

outer, graph_file, evaluated_file = map(lambda p:Path(p).resolve(),sys.argv[1:4])
target_os=sys.argv[4]
rules=Path(__file__).resolve().parents[3]
root=outer/'upstream'
graph={(r['project'],r['framework']):r for r in json.loads(graph_file.read_text()) if r['framework']}
contract_file=Path(__file__).with_name('runtime-contracts.json')
evaluated=[r for r in json.loads(evaluated_file.read_text()) if r.get('framework')]
projects={r['project'] for r in evaluated}
reviewed=json.loads(contract_file.read_text())
reviewed.update(json.loads(Path(__file__).with_name('runtime-full-contracts.json').read_text()))
def call(rule,**attrs):return rule+'('+','.join(k+'='+(str(v) if isinstance(v,bool) else json.dumps(v)) for k,v in attrs.items())+')'
def tag(project):return project.removesuffix('.csproj').replace('/','_')
text=(root/'BUILD.bazel').read_text();records={};kept=[];selected={}
if (outer/'project-bindings.json').exists():
    text += '\n' + '\n'.join(call(v['rule'], **v['attributes']) for v in json.loads((outer/'project-bindings.json').read_text()).values())
for line in text.splitlines():
    if line.startswith(('msbuild_toolchain(', 'toolchain(')):continue
    if not line or line.startswith('load('):kept.append(line);continue
    node=ast.parse(line).body[0].value;attrs={k.arg:ast.literal_eval(k.value) for k in node.keywords};rule=node.func.id
    records[attrs['name']]=(rule,attrs)
    if attrs.get('project') in projects:
        assert attrs['project'] not in selected, 'Explicit configured variants required'
        selected[attrs['project']]=attrs
        suffix = '' if rule == 'msbuild_binary' else '_' + attrs['target_framework'].replace('.', '_')
        kept.append(call('alias',name=attrs['name'],actual=':'+tag(attrs['project'])+suffix))
        continue
    if rule in ['msbuild_library','msbuild_binary','msbuild_test']:
        attrs['linux_worker']=target_os=='linux';attrs['msbuild_properties']['TargetOS']=target_os
        # Match the upstream private project edges explicitly for the new runner.
        row=graph[(attrs['project'],attrs['target_framework'])]
        private=[]
        for ref in row['references']:
            if ref['metadata'].get('PrivateAssets','').lower()!='all':continue
            path=Path(ref['include'].replace('\\','/'))
            # Resolve from the original graph root, recorded in its assets path.
            original=Path(row['assets']);source=next(p for p in original.parents if p.name=='artifacts').parent
            path=Path(os.path.normpath(source/Path(row['project']).parent/path)).relative_to(source).as_posix()
            prefix=':'+tag(path)+'_'
            private += [dep for dep in attrs['deps'] if dep.startswith(prefix)]
        attrs['deps']=[d for d in attrs['deps'] if d not in private]
        if private:attrs['implementation_deps']=private
    kept.append(call(rule,**attrs))
# Module lives at the source root so production sync emits one root package.
(root/'MODULE.bazel').write_text('module(name="pipelines_sync")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(rules))+')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",version="10.0.400")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
shutil.copyfile(rules/'.bazelversion',root/'.bazelversion')
if (outer/'runtime').exists():shutil.move(outer/'runtime',root/'runtime')
evaluated = [r for r in evaluated if r['framework'] == selected[r['project']]['target_framework']]
assert len(evaluated) == len(selected)
locked=set();mapping={'projects':{},'packages':{},'tests':{}};sync_bindings=set()
for row in evaluated:
    project=row['project'];previous=selected[project]
    locked.update(records[previous['package_lock'][1:]][1]['packages'])
    properties={k:v for k,v in previous['msbuild_properties'].items() if k not in ['SharedCompilationId', 'UseSharedCompilation']};properties['TargetOS']=target_os
    binding={'targetFrameworks':[row['framework']],'outputMode':previous['output_mode'],'packageReferencePaths':previous.get('package_reference_paths', {}),'transitiveCompileReferences':previous.get('transitive_compile_references', True),'references':{},'properties':properties,'adapterImports':[':layout.targets'],'documents':{},'projectReferences':{},'bindings':previous.get('bindings',[]),'layoutBindings':previous.get('layout_bindings',{}),'evaluationItems':[]}

    # Reviewed categories: repository subset routing, packaging/binplace,
    # APICompat transforms, compiler-visible scalar settings and test launch.
    known='WorkloadSdkBandVersions SubsetName SupportedPlatform SupportedNETCoreAppTargetFramework NetCoreAppLibrary NetCoreAppLibraryGenerator AspNetCoreAppLibrary WindowsDesktopCoreAppLibrary CorehostProjectToBuild ManagedProjectToBuild InstallerProjectToBuild PkgprojProjectToBuild ProjectToBuild SharedFrameworkProjectToBuild TestProjectToBuild ProjectExclusions _CrossToolSubset _frameworkProjectReference _projectReferenceWithFilename _projectReferenceExcludedWithFilename _ProjectReferenceWithOriginalIdentity AdditionalLibPackageExcludes AdditionalSymbolPackageExcludes ApiCompatContractAssemblyReferences ApiCompatExcludeAttributesFile ApiCompatLeftAssembliesTransformationPattern ApiCompatRightAssembliesTransformationPattern AssemblyAttribute BinPlaceTargetFrameworks CompilerVisibleProperty CoverageExcludeByFile CoverageIncludeDirectory ILLinkSubstitutionsXmls NetFxReference NETStandardCompatError PackageDownload SourceRoot MonoAotCrossCompiler SetScriptCommands EnabledGenerators RdXmlFile ApiCompatSuppressionFile BinPlaceDir GenFacadesIgnoreMissingType GenFacadesOmitType ILLinkDescriptorsLibraryBuildXml ILLinkLinkAttributesXmls ILLinkSuppressionsLibraryBuildXml ILLinkSuppressionsXmls PackageDownloadAndReference _DebugSymbolToMove _DebugSymbolToMoveToUpdate _ILLinkDescriptorsFilePaths _coreLibProjectReference'.split()
    binding['evaluationItems']=known
    if project == 'src/coreclr/System.Private.CoreLib/System.Private.CoreLib.csproj':
        binding['platform'] = 'arm64'
    for doc in row['documents']:
        if doc['targets'] or doc['tasks']:
            observed={k:doc[k] for k in ['sha256','targets','tasks']}
            assert reviewed.get(doc['path'].lower() if doc['path'].startswith('.nuget/') else doc['path'])==observed, ('Unreviewed custom document',doc['path'])
            binding['documents'][doc['path']]=dict(observed)
    # Retain the previously qualified non-item file inputs (APICompat, link
    # templates, settings and reference project definitions).
    binding['documents']['Directory.Build.targets']['inputs']=list(previous['msbuild_imports'])
    # NativeAOT-only directives remain declared files even in this JIT slice.
    for item in row['items']:
        if item['type'] == 'RdXmlFile':
            path=(root/Path(project).parent/item['include'].replace('\\','/')).resolve().relative_to(root).as_posix()
            assert (root/path).is_file(), path
            binding['documents']['Directory.Build.targets']['inputs'].append(path)
    for ref in row['items']:
        if ref['type']!='ProjectReference':continue
        path=Path(ref['include'].replace('\\','/'))
        source=next(p for p in Path(row['assets']).parents if p.name=='artifacts').parent
        path=Path(os.path.normpath(source/Path(project).parent/path)).relative_to(source).as_posix()
        meta=ref['metadata']
        if meta.get('OutputItemType') == '_contractSourceFilesGroup':
            labels = [label for label in previous['items'] if records[label[1:]][1]['item_type'] == '_contractSourceFilesGroup']
            assert labels
            binding['projectReferences'][path] = dict(role='items', labels=labels, outputItemType=meta['OutputItemType'], targets=meta['Targets'])
            continue
        if meta.get('OutputItemType')=='Analyzer':role='analyzer';labels=previous['analyzers']
        elif meta.get('OutputItemType')=='ResolvedMatchingContract':role='output';labels=previous['project_outputs']
        elif meta.get('ReferenceOutputAssembly','').lower()=='false':role='tool';labels=previous['tools']
        else:role='private' if meta.get('PrivateAssets','').lower()=='all' else 'compile';labels=previous['deps']
        def producer(label):
            attrs = records[label[1:]][1]
            if 'project' in attrs: return attrs['project']
            edge = attrs.get('assembly') or attrs.get('implementation')
            return producer(edge) if edge else None
        candidates=[label for label in labels if producer(label) == path];assert len(candidates)==1,(path,candidates)
        binding['projectReferences'][path]={'role':role,'label':candidates[0]}
    for item in row['items']:
        if item['type'] != 'Reference': continue
        parts = Path(item['include']).parts
        assert 'packages' in parts, item
        relative = '/'.join(parts[parts.index('packages') + 1:])
        package, version, asset = relative.split('/', 2)
        assert asset in binding['packageReferencePaths'][package]
        labels = [':' + name for name, (kind, attrs) in records.items() if kind == 'msbuild_nuget_package' and attrs['package_id'].lower() == package and attrs['version'] == version]
        assert len(labels) == 1, item
        # The selected file is already an explicit package-lock input; it is
        # not a bare assembly-name Reference to convert into a PackageReference.
    for item in row['items']:
        if item['type']!='PackageReference':continue
        identity=item['include'];matches=[]
        for label in previous['deps']:
            rule,attrs=records[label[1:]]
            if rule!='msbuild_nuget_dependencies':continue
            package=records[attrs['package'][1:]][1]
            if package['package_id'].lower()==identity.lower():matches.append((label,package))
        assert len(matches)==1,(identity,matches)
        label,package=matches[0];mapping['packages'][identity+'/'+package['version']]={'label':label,'roles':['deps','build_deps','analyzers']}
    for package in row['packages']:
        identity = package['id'] + '/' + (package['versionOverride'] or package['version'])
        if identity in mapping['packages']: continue
        matches = [':' + name for name, (kind, attrs) in records.items() if kind == 'msbuild_nuget_package' and attrs['package_id'].lower() == package['id'].lower() and attrs['version'] == package['version']]
        assert len(matches) == 1, identity
        mapping['packages'][identity] = dict(label=matches[0], roles=['build_deps'])
    mapping['projects'][project]=binding;sync_bindings.update(binding['bindings'])
    if 'test_runner' in previous:
        binding['runtimeHost']='//runtime:host'
        if project == 'src/libraries/System.Collections.Immutable/tests/System.Collections.Immutable.Tests.csproj':
            # TestUtilities and Immutable reach both the direct implementation
            # and its public contract pair. Select the reviewed pair explicitly.
            binding['assemblySelections']=[':src_libraries_'+name+'_src_'+name+'_net10.0_paired' for name in ['System.Collections','System.Threading']]
        mapping['tests'][project]={'protocol':'vstest','outputType':'exe','runner':previous['test_runner'],'adapters':previous['test_adapters'],'settingsOutput':'.runsettings'}
# Generated task producers must exist before sync can analyze their bindings.
# Bootstrap their dependency closure through the same production generator.
seen = set()
tool_projects = set()
def visit_tool(value):
    if isinstance(value, dict):
        for child in value.values(): visit_tool(child)
    elif isinstance(value, list):
        for child in value: visit_tool(child)
    elif isinstance(value, str) and value.startswith(':') and value[1:] in records and value not in seen:
        seen.add(value)
        _, attrs = records[value[1:]]
        if attrs.get('project') in projects: tool_projects.add(attrs['project'])
        visit_tool({k:v for k,v in attrs.items() if k != 'name'})
for label in sorted(sync_bindings): visit_tool(label)
if tool_projects:
    assert all(not mapping['projects'][p]['bindings'] for p in tool_projects), 'Task bootstrap itself needs a declared external tool'
    bootstrap = dict(mapping, projects={p:mapping['projects'][p] for p in sorted(tool_projects)}, tests={})
    (root/'sync-tools.json').write_text(json.dumps(bootstrap, indent=2)+'\n')
    kept.append(call('msbuild_sync', name='sync_tools', projects=sorted(tool_projects), mappings='sync-tools.json', package_lock=':sync_packages'))
kept.insert(0,'load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")')
kept.append(call('msbuild_package_lock',name='sync_packages',packages=sorted(locked)))
kept.append(call('msbuild_sync',name='sync',projects=sorted(projects),mappings='sync.json',package_lock=':sync_packages',bindings=sorted(sync_bindings)))
(root/'BUILD.bazel').write_text('\n'.join(kept)+'\n')
(root/'sync.json').write_text(json.dumps(mapping,indent=2)+'\n')
print(root)
