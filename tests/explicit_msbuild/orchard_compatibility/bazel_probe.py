import json,os,hashlib,shutil,subprocess
from pathlib import Path
root=Path('/orchard-work'); sdk=os.environ['RULES_MSBUILD_DOTNET_ROOT'];bazel=os.environ['RULES_MSBUILD_BAZEL'];evidence=Path('/evidence')
rows=json.loads((evidence/'evaluated.json').read_text());by={Path(x['project']).stem:x for x in rows}
(root/'MODULE.bazel').write_text(f'''module(name="orchard_compatibility")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path="/workspace")
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(sdk)},include_runtime_closure=False)
register_toolchains("//:registered")
''')
header='''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_nuget_package","msbuild_items")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
'''
generator=by['OrchardCore.SourceGenerators'];leaf=by['OrchardCore.ContentPreview.Abstractions']
assets=json.loads((root/Path(generator['project']).parent/'obj/project.assets.json').read_text());target=next(iter(assets['targets'].values()))
packages=root/'compat-packages';packages.mkdir(exist_ok=True)
for key,record in target.items():
 if record.get('type')!='package':continue
 name,version=key.split('/');archive_name=f'{name.lower()}.{version}.nupkg';archive=Path('/tmp/nuget')/name.lower()/version/archive_name;shutil.copyfile(archive,packages/archive_name)
 header+='msbuild_nuget_package('+','.join(k+'='+json.dumps(v) for k,v in dict(name=name.lower(),package_id=name,version=version,archive='compat-packages/'+archive_name,archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),content_hash=assets['libraries'][key]['sha512'],deps=[':'+x.lower() for x in record.get('dependencies',{})]).items())+')\n'

def rule(name,row,extra):
 paths=[str((Path(row['project']).parent/p['include']).as_posix()) if not Path(p['include']).is_absolute() else str(Path(p['include']).relative_to(root)) for p in row['compile']]
 extra['items']=[':'+name+'_additional'] if row['additional'] else []
 pre='msbuild_items(name='+json.dumps(name+'_additional')+',item_type="AdditionalFiles",srcs='+json.dumps([str(Path(row['project']).parent/p['include']) for p in row['additional']])+')\n' if row['additional'] else ''
 return pre+'msbuild_library('+','.join(k+'='+json.dumps(v) for k,v in dict(name=name,project=row['project'],target_framework=row['framework'],srcs=paths,msbuild_imports=row['imports']+['.editorconfig'],framework_refs=[p['include'] for p in row['frameworks'] if p['metadata'].get('IsImplicitlyDefined','').lower()!='true'],lang_version='latest',nullable='disable',**extra).items())+',linux_worker=True)\n'
base=header+rule('sourcegen',generator,dict(deps=[':'+p['include'].lower() for p in generator['packages']],build_deps=[':'+p['include'].lower() for p in generator['packages']],analyzers=[':'+p['include'].lower() for p in generator['packages']],package_private_assets={p['include']:'all' for p in generator['packages'] if p['metadata'].get('PrivateAssets','').lower()=='all'}))
reports=[]
def run(case,text,label,expect):
 (root/'BUILD.bazel').write_text(text)
 p=subprocess.run([bazel,'--output_base=/tmp/orchard-compat-base','--ignore_all_rc_files','build',label,'--repository_cache=/tmp/repository-cache','--disk_cache=','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1'],cwd=root,capture_output=True,text=True,timeout=240)
 output=p.stdout+p.stderr;(evidence/(case+'.log')).write_text(output)
 assert (p.returncode==0) if expect is None else (p.returncode!=0 and expect in output),(case,output[-7000:])
 reports.append(dict(case=case,exit=p.returncode,expected=expect));print(case,expect,flush=True)
run('analyzer-provider',base+rule('leaf',leaf,dict(analyzers=[':sourcegen'])),'//:leaf','MSBuildPackageInfo')
run('generator-as-dependency',base+rule('leaf',leaf,dict(deps=[':sourcegen'])),'//:leaf','requires matching target frameworks')
run('private-assets',base,'//:sourcegen',None)
probe=root/'CompatibilityProbe';probe.mkdir(exist_ok=True)
(probe/'Directory.Build.props').write_text('<Project />')
(probe/'Directory.Packages.props').write_text('<Project><PropertyGroup><ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally><CentralPackageTransitivePinningEnabled>true</CentralPackageTransitivePinningEnabled></PropertyGroup><ItemGroup><PackageVersion Include="StyleCop.Analyzers" Version="1.1.118" /></ItemGroup></Project>')
(probe/'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="StyleCop.Analyzers" /></ItemGroup></Project>')
(probe/'Class.cs').write_text('public class Class {}')
synthetic=header+'msbuild_library(name="cpm_probe",project="CompatibilityProbe/Probe.csproj",target_framework="net10.0",srcs=["CompatibilityProbe/Class.cs"],msbuild_imports=["CompatibilityProbe/Directory.Build.props","CompatibilityProbe/Directory.Packages.props"],analyzers=[":stylecop.analyzers"],linux_worker=True)\n'
run('central-package-versions',synthetic,'//:cpm_probe',None)
(evidence/'bazel-report.json').write_text(json.dumps(reports,indent=2))
subprocess.run([bazel,'--output_base=/tmp/orchard-compat-base','--ignore_all_rc_files','shutdown'],cwd=root,check=True)
