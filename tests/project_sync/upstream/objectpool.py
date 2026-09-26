"""Prepare the pinned ObjectPool slice for production msbuild_sync.

Inputs: bootstrapped/raw-built ASP.NET checkout, evaluation inventory, fresh output.
Acquisition/contract authoring is fixture setup; project/source emission is done
only by msbuild_sync. No generated BUILD declarations are edited after sync.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

source, inventory, out = [Path(p).resolve() for p in sys.argv[1:4]]
vstest = Path(sys.argv[4]).resolve()
rules = Path(__file__).resolve().parents[3]
rows = json.loads(inventory.read_text())
reviewed = json.loads(Path(__file__).with_name('objectpool-contracts.json').read_text())
out.mkdir(parents=True, exist_ok=False)
workspace = out / 'workspace'
shutil.copytree(source, workspace, ignore=shutil.ignore_patterns('.git', '.dotnet', 'artifacts', 'bin', 'obj'))
(workspace/'locked-packages').mkdir()
def put(path, text):
    p=workspace/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
def call(rule, **attrs):
    return rule+'('+','.join(k+'='+(str(v) if isinstance(v,bool) else json.dumps(v)) for k,v in attrs.items())+')'
def tag(path):return path.removesuffix('.csproj').replace('/','_')
archives={};closures={};mappings={'projects':{},'packages':{},'tests':{}}
package_roots=set()
for row in rows:
    assets=json.loads(Path(row['assets']).read_text());package_roots.update(assets['packageFolders'])
for row in rows:
    assets=json.loads(Path(row['assets']).read_text())
    locked={k.lower().split('/')[0]:(k,v) for k,v in assets['targets']['net10.0'].items() if v['type']=='package'}
    for download in assets['project']['frameworks']['net10.0'].get('downloadDependencies',[]):
        versions={v.strip() for v in download['version'].strip('[]').split(',')};assert len(versions)==1
        version=versions.pop()
        locked.setdefault(download['name'].lower(),(download['name']+'/'+version,{}))
    for doc in row['documents']:
        if doc['path'].startswith('.nuget/packages/'):
            package,version=doc['path'].split('/')[2:4];locked.setdefault(package,(package+'/'+version,{}))
    for key,_ in locked.values():
        package,version=key.split('/');filename=package.lower()+'.'+version+'.nupkg'
        archive=next(Path(root)/package.lower()/version/filename for root in package_roots if (Path(root)/package.lower()/version/filename).exists())
        shutil.copyfile(archive,workspace/'locked-packages'/filename)
        data=archive.read_bytes();label='package_'+package.lower().replace('.','_')+'_'+version.replace('.','_')
        archives[key.lower()]=(label,call('msbuild_nuget_package',name=label,package_id=package,version=version,archive='locked-packages/'+filename,archive_sha256=hashlib.sha256(data).hexdigest(),content_hash=base64.b64encode(hashlib.sha512(data).digest()).decode()))
    memo={}
    def closure(package):
        if package in memo:return memo[package]
        key,data=locked[package];deps=sorted(closure(d.lower()) for d in data.get('dependencies',{}) if d.lower() in locked)
        name='closure_'+hashlib.sha256(json.dumps([key,deps]).encode()).hexdigest()[:20]
        closures[name]=call('msbuild_nuget_dependencies',name=name,package=':'+archives[key.lower()][0],deps=deps);memo[package]=':'+name;return memo[package]
    row['_packages']={p:closure(p) for p in locked}
    for item in row['items']:
        if item['type']=='PackageReference':
            key,_=locked[item['include'].lower()]
            mappings['packages'][key]={'label':closure(item['include'].lower()),'roles':['deps','build_deps','analyzers']}
# These item kinds were reviewed in the pinned import chains. They describe
# repository routing, packaging/Helix destinations or reference bookkeeping, not
# additional compiler file inputs. Sources/content are handled separately.
evaluation_items='CreateDirectory RemoteAssetBaseURL RequiresDelayedBuild ProjectReferenceProvider AspNetCoreAppReference AspNetCoreAppReferenceAndPackage AspNetCoreShippingAssembly ExternalAspNetCoreAppReference LatestPackageReference _LatestRuntimePackageReference _TransitiveExternalAspNetCoreAppReference _CompilationOnlyReference _OriginalReferences Service _ImplicitPackageReference _TestArchitectureItems HelixAvailablePlatform HelixAvailableTargetQueue HelixContent HelixProjectPlatform ContentWithTargetPath'.split()
props={'RepositoryCommit':'7387de91234d3ef751fa50b3d1bfede4130213ff','SourceRevisionId':'7387de91234d3ef751fa50b3d1bfede4130213ff'}
bootstrap=rows[-1]
imports=[]
for doc in bootstrap['documents']:
    if not doc['path'].startswith('.nuget/') and doc['path']!=bootstrap['project']:imports.append(doc['path'])
imports+=['global.json','eng/tools/GenerateFiles/Directory.Build.props.in','eng/tools/GenerateFiles/Directory.Build.targets.in','eng/tools/GenerateFiles/dotnet-tools.json.in']
for row in rows[:-1]:
    project=row['project']
    binding={'targetFrameworks':['net10.0'],'properties':props,'evaluationItems':evaluation_items,'adapterImports':[':layout.targets'],'directories':['artifacts/installers/Release','artifacts/VSSetup/Release'],'documents':{},'references':{},'projectReferences':{}}
    for doc in row['documents']:
        if doc['targets'] or doc['tasks']:
            observed={k:doc[k] for k in ['sha256','targets','tasks']}
            assert reviewed.get(doc['path'].lower() if doc['path'].startswith('.nuget/') else doc['path'])==observed, ('Unreviewed custom document',doc['path'])
            binding['documents'][doc['path']]=dict(observed)
            binding['documents'][doc['path']]['inputs']=[]
    # Track ancestor analyzer configuration plus repository API baselines.
    extra=[p.relative_to(workspace).as_posix() for p in workspace.rglob('.editorconfig')]
    extra += [p.relative_to(workspace).as_posix() for p in (workspace/Path(project).parent).glob('PublicAPI*.txt')]
    binding['documents']['Directory.Build.targets']['inputs']=extra
    for item in row['items']:
        if item['type']=='Reference':
            identity=item['include'];binding['references'][identity]=({'role':'package','label':row['_packages'][identity.lower()],'roles':['build_deps','analyzers']} if identity.lower() in row['_packages'] else {'role':'framework'})
        elif item['type']=='ProjectReference':
            path=Path(item['include']).relative_to(source).as_posix();binding['projectReferences'][path]={'role':'compile','label':':'+tag(path)}
    mappings['projects'][project]=binding
    if '/test/' in project:binding['itemPaths']={'NuGet.config':'qualification-data/NuGet.config'}
    if '/test/' in project:mappings['tests'][project]={'protocol':'vstest','runner':':vstest','adapters':[':xunit'],'outputDirectories':['test-logs']}
put('sync.json',json.dumps(mappings,indent=2)+'\n')
put('layout.targets',(rules/'tests/explicit_msbuild/aspnetcore/layout.targets').read_text().replace('<PropertyGroup>','<PropertyGroup><LoggingTestingFileLoggingDirectory>test-logs</LoggingTestingFileLoggingDirectory>',1))
put('bootstrap.targets','''<Project><PropertyGroup><NetCoreTargetingPackRoot>$([System.IO.Path]::GetFullPath('$(MSBuildToolsPath)/../../packs'))/</NetCoreTargetingPackRoot></PropertyGroup><Target Name="BindBootstrapOutputs" BeforeTargets="GenerateDirectoryBuildFiles"><PropertyGroup><ArtifactsShippingPackagesDir>%24(RepoRoot)artifacts/packages/Release/Shipping/</ArtifactsShippingPackagesDir><BaseOutputPath>$([System.IO.Path]::GetDirectoryName('$(BootstrapProps)'))/</BaseOutputPath><ConfigDirectory>$([System.IO.Path]::GetDirectoryName('$(BootstrapTools)'))/</ConfigDirectory></PropertyGroup></Target></Project>''')
put('MODULE.bazel','module(name="objectpool_sync")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(rules))+')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",version="10.0.400")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
shutil.copyfile(rules/'.bazelversion',workspace/'.bazelversion')
lines=['load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")','load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package","msbuild_nuget_dependencies","msbuild_package_lock","msbuild_generate","msbuild_test_tool")']
lines += [v[1] for v in archives.values()]+list(closures.values())
lines += [call('msbuild_package_lock',name='packages',packages=[':'+v[0] for v in archives.values()])]
lines += [call('msbuild_generate',name='bootstrap',project=bootstrap['project'],target_framework='net10.0',msbuild_imports=sorted(set(imports)),adapter_imports=['bootstrap.targets'],package_lock=':packages',deps=list(bootstrap['_packages'].values()),build_deps=list(bootstrap['_packages'].values()),analyzers=list(bootstrap['_packages'].values()),reference_packages=[bootstrap['_packages']['microsoft.codeanalysis.publicapianalyzers']],package_private_assets={'Microsoft.DotNet.Build.Tasks.Templating':'all','Microsoft.CodeAnalysis.PublicApiAnalyzers':'all'},targets=['GenerateDirectoryBuildFiles'],outputs=['Directory.Build.props','Directory.Build.targets','dotnet-tools.json'],output_properties={'BootstrapProps':'Directory.Build.props','BootstrapTools':'dotnet-tools.json'},msbuild_properties=props)]
inputs={}
for name in ['props','targets']:
    lines.append(call('filegroup',name='bootstrap_'+name,srcs=[':bootstrap'],output_group='Directory.Build.'+name));inputs[':bootstrap_'+name]='artifacts/bin/GenerateFiles/Directory.Build.'+name
lines.append(call('msbuild_sync',name='sync',projects=[r['project'] for r in rows[:-1]],mappings='sync.json',inputs=inputs,package_lock=':packages'))
data=vstest.read_bytes();shutil.copyfile(vstest,workspace/'locked-packages/vstest.nupkg')
lines.append(call('msbuild_nuget_package',name='vstest_package',package_id='Microsoft.TestPlatform.CLI',version='17.14.1',archive='locked-packages/vstest.nupkg',archive_sha256=hashlib.sha256(data).hexdigest(),content_hash=base64.b64encode(hashlib.sha512(data).digest()).decode()))
lines.append(call('msbuild_test_tool',name='vstest',package=':vstest_package',path='contentFiles/any/net9.0/vstest.console.dll'))
with zipfile.ZipFile(workspace/'locked-packages/xunit.runner.visualstudio.3.1.3.nupkg') as z:
    paths={str(Path(p).parent) for p in z.namelist() if p.endswith('xunit.runner.visualstudio.testadapter.dll') and '/net4' not in p}
assert len(paths)==1,paths
lines.append(call('msbuild_test_tool',name='xunit',package=':'+archives['xunit.runner.visualstudio/3.1.3'][0],path=paths.pop()))
put('BUILD.bazel','\n'.join(lines)+'\n')
(out/'package-index.json').write_text(json.dumps({k:v[0] for k,v in archives.items()},indent=2))
print(workspace)
