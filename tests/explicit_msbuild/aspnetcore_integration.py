"""Pinned ASP.NET Core bootstrap and reference-resolution integration slice."""
import base64,hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];folder=Path(sys.argv[1]).resolve();folder.mkdir(parents=True);src=folder/'src';src.mkdir();raw=folder/'raw';raw.mkdir();sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);bazel=os.environ['RULES_MSBUILD_BAZEL'];upstream=Path(sys.argv[2]);packages=folder/'nuget';rows=[]
def call(args,cwd=None,ok=True):
 p=subprocess.run(list(map(str,args)),cwd=cwd or src,capture_output=True,text=True,timeout=240)
 if ok:assert p.returncode==0,(args,(p.stdout+p.stderr)[-7000:])
 else:assert p.returncode!=0,args
 return p.stdout if ok else p.stdout+p.stderr
assert call(['git','rev-parse','HEAD'],upstream).strip()=='7387de91234d3ef751fa50b3d1bfede4130213ff'
for root in [src,raw]:
 (root/'bootstrap').mkdir();(root/'app').mkdir()
 for name in ['GenerateFiles.csproj','Directory.Build.props.in','Directory.Build.targets.in','dotnet-tools.json.in']:shutil.copyfile(upstream/'eng/tools/GenerateFiles'/name,root/'bootstrap'/name)
 shutil.copyfile(upstream/'eng/targets/ResolveReferences.targets',root/'app/ResolveReferences.targets')
shutil.copyfile(upstream/'NuGet.config',raw/'NuGet.config')
version='10.0.0-beta.25515.111'
props={'MicrosoftDotNetBuildTasksTemplatingVersion':version,'DefaultNetCoreTargetFramework':'net10.0','AspNetCorePatchVersion':'1','DotnetDumpVersion':'9.0.621003','DotnetEfVersion':'10.0.0','DotnetServeVersion':'1.10.192','TargetingPackVersion':'10.0.0','SharedFxVersion':'10.0.0','MicrosoftNETCoreAppRefVersion':'10.0.0','MicrosoftPlaywrightCLIVersion':'1.2.3','BundledNETCoreAppPackageVersion':'10.0.0','SupportedRuntimeIdentifiers':'linux-arm64'}
rawprops=['-p:'+k+'='+v for k,v in props.items()]+['-p:RestorePackagesPath='+str(packages),'-p:NuGetAudit=false']
call([sdk/'dotnet','restore','bootstrap/GenerateFiles.csproj',*rawprops],raw)
# Restore the external reference separately; the actual raw build uses upstream resolution.
(raw/'Package.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="Microsoft.Extensions.Primitives" Version="10.0.0" /><PackageDownload Include="Microsoft.NETCore.App.Ref;Microsoft.NETCore.App.Host.linux-arm64" Version="[10.0.0]" /></ItemGroup></Project>')
call([sdk/'dotnet','restore','Package.csproj','-p:RestorePackagesPath='+str(packages),'-p:NuGetAudit=false'],raw)
module=f'''module(name="aspnetcore_integration")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(str(sdk))},include_runtime_closure=False)
register_toolchains("//:registered")
''';(src/'MODULE.bazel').write_text(module)
build='''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_generate","msbuild_binary","msbuild_nuget_package","msbuild_package_lock")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
'''
for label,id,v,sha in [('templating','Microsoft.DotNet.Build.Tasks.Templating',version,'2f633353a3929728e4d4b1211973922c01f6c906fbf888103ff7ba708b62982d'),('primitives','Microsoft.Extensions.Primitives','10.0.0','0eea74f0a729b4b8e59e9379b79ffffa9e27f0551381102ae27ff0d6ceaeb3e2'),('netref','Microsoft.NETCore.App.Ref','10.0.0','8f2b6f7741a571640ba2598dddb9c15ca8a3a0020240d024f2ce1ed264fa0a9b'),('nethost','Microsoft.NETCore.App.Host.linux-arm64','10.0.0','44b0d61bbe076831487e7d23c90a05ea27f56a90b7d62e564ebc57a7cf4d0038')]:
 archive=packages/id.lower()/v/(id.lower()+'.'+v+'.nupkg');data=archive.read_bytes();assert hashlib.sha256(data).hexdigest()==sha;(src/(label+'.nupkg')).write_bytes(data)
 build+=f'msbuild_nuget_package(name="{label}",package_id="{id}",version="{v}",archive="{label}.nupkg",archive_sha256="{sha}",content_hash="{base64.b64encode(hashlib.sha512(data).digest()).decode()}")\n'
build+='''msbuild_generate(name="bootstrap",project="bootstrap/GenerateFiles.csproj",target_framework="net10.0",msbuild_imports=glob(["bootstrap/*.in"]),adapter_imports=["bootstrap/outputs.targets"],build_deps=[":templating"],package_private_assets={"Microsoft.DotNet.Build.Tasks.Templating":"all"},targets=["GenerateDirectoryBuildFiles"],outputs=["Directory.Build.props","Directory.Build.targets","dotnet-tools.json"],output_properties={"GeneratedProps":"Directory.Build.props","GeneratedTools":"dotnet-tools.json"},msbuild_properties='''+repr(props)+''',linux_worker=True)
filegroup(name="props",srcs=[":bootstrap"],output_group="Directory.Build.props")
filegroup(name="targets",srcs=[":bootstrap"],output_group="Directory.Build.targets")
msbuild_package_lock(name="app_lock",packages=[":primitives",":netref",":nethost"])
msbuild_binary(name="App",package_lock=":app_lock",project="app/App.csproj",target_framework="net10.0",srcs=["app/Program.cs"],msbuild_imports=["app/ResolveReferences.targets"],import_paths={":props":"artifacts/bin/GenerateFiles/Directory.Build.props",":targets":"artifacts/bin/GenerateFiles/Directory.Build.targets"},reference_packages=[":primitives"],msbuild_properties={"UpdateAspNetCoreKnownFramework":"false"},linux_worker=True)
'''
(src/'BUILD.bazel').write_text(build)
(src/'bootstrap/outputs.targets').write_text('''<Project><Target Name="BindBootstrapOutputs" BeforeTargets="GenerateDirectoryBuildFiles"><PropertyGroup><BaseOutputPath>$([System.IO.Path]::GetDirectoryName('$(GeneratedProps)'))/</BaseOutputPath><ConfigDirectory>$([System.IO.Path]::GetDirectoryName('$(GeneratedTools)'))/</ConfigDirectory></PropertyGroup></Target></Project>''')
project='''<Project Sdk="Microsoft.NET.Sdk"><Import Project="../artifacts/bin/GenerateFiles/Directory.Build.props"/><PropertyGroup><TargetFramework>$(DefaultNetCoreTargetFramework)</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><Reference Include="Microsoft.Extensions.Primitives"/><LatestPackageReference Include="Microsoft.Extensions.Primitives" Version="10.0.0"/></ItemGroup><Import Project="ResolveReferences.targets"/><Import Project="../artifacts/bin/GenerateFiles/Directory.Build.targets"/></Project>'''
for root in [raw,src]:
 (root/'app/App.csproj').write_text(project);(root/'app/Program.cs').write_text('System.Console.WriteLine(new Microsoft.Extensions.Primitives.StringValues("upstream-reference")); System.Console.WriteLine(typeof(Program).Assembly.GetName().Version);')
base=folder/'base';startup=[bazel,'--output_base='+str(base),'--ignore_all_rc_files'];flags=['--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE'],'--disk_cache='+str(folder/'cache'),'--strategy=MSBuildGenerate=worker','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildGenerate=1','--worker_max_instances=MSBuildAssembly=1']
def check(name):
 rawout=raw/'artifacts/bin/GenerateFiles';rawout.mkdir(parents=True,exist_ok=True)
 call([sdk/'dotnet','msbuild','bootstrap/GenerateFiles.csproj','-t:GenerateDirectoryBuildFiles',*rawprops,'-p:BaseOutputPath='+str(rawout)+'/', '-p:ConfigDirectory='+str(rawout)+'/'],raw)
 call([sdk/'dotnet','build','app/App.csproj','-c','Release','-p:ProduceReferenceAssembly=true','-p:UpdateAspNetCoreKnownFramework=false','-p:RestorePackagesPath='+str(packages),'-p:NuGetAudit=false'],raw)
 expected=call([sdk/'dotnet',raw/'app/bin/Release/net10.0/App.dll'],raw).strip()
 output=call(startup+['run','//:App']+flags).strip();assert output==expected,(output,expected)
 hashes={}
 for file in ['Directory.Build.props','Directory.Build.targets','dotnet-tools.json']:
  actual=src/'bazel-bin/bootstrap.generated'/file;assert actual.read_bytes()==(rawout/file).read_bytes(),file;hashes[file]=hashlib.sha256(actual.read_bytes()).hexdigest()
 ref=src/'bazel-bin/App.reference/App.dll';assert ref.read_bytes()==(raw/'app/obj/Release/net10.0/ref/App.dll').read_bytes()
 rows.append(dict(case=name,output=output,referenceHash=hashlib.sha256(ref.read_bytes()).hexdigest(),generated=hashes));print(name,'parity',flush=True)
try:
 check('initial')
 for root in [raw,src]:
  p=root/'bootstrap/Directory.Build.props.in';p.write_text(p.read_text().replace('<PropertyGroup>','<PropertyGroup><AssemblyVersion>2.0.0.0</AssemblyVersion>',1))
 check('template-edit');assert rows[0]['referenceHash']!=rows[1]['referenceHash']
 # The binding is required and must match a real Reference declaration.
 (src/'BUILD.bazel').write_text(build.replace('reference_packages=[":primitives"]','deps=[":primitives"]'))
 failure=call(startup+['build','//:App']+flags,ok=False);assert 'Undeclared assembly/analyzer dependency' in failure,failure
 (src/'BUILD.bazel').write_text(build);(src/'app/App.csproj').write_text(project.replace('<Reference Include="Microsoft.Extensions.Primitives"/>',''))
 failure=call(startup+['build','//:App']+flags,ok=False);assert 'requires exactly one matching Reference' in failure,failure
 (src/'app/App.csproj').write_text(project.replace('<Reference Include="Microsoft.Extensions.Primitives"/>','<Reference Include="Microsoft.Extensions.Primitives" HintPath="undeclared.dll"/>'))
 failure=call(startup+['build','//:App']+flags,ok=False);assert 'Unsupported bound Reference metadata: HintPath' in failure,failure
 (src/'app/App.csproj').write_text(project);call(startup+['build','//:App']+flags)
 call(startup+['shutdown']);relocated=folder/'relocated';shutil.copytree(src,relocated,ignore=shutil.ignore_patterns('bazel-*'));shutil.rmtree(src);shutil.rmtree(base);shutil.rmtree(raw);src=relocated
 startup=[bazel,'--output_base='+str(folder/'recovery'),'--output_user_root='+str(folder/'fresh-user'),'--ignore_all_rc_files']
 output=call(startup+['run','//:App','--execution_log_json_file='+str(folder/'recovery.json')]+flags).strip();assert output==rows[-1]['output']
 text=(folder/'recovery.json').read_text();decoder=json.JSONDecoder();actions=[]
 while text.strip():
  action,end=decoder.raw_decode(text.lstrip());text=text.lstrip()[end:]
  if action.get('mnemonic') in ('MSBuildGenerate','MSBuildAssembly'):actions.append(action)
 assert len(actions)==2 and all(a.get('cacheHit') for a in actions),actions
 rows.append(dict(case='binding-controls-and-relocated-cache-recovery',cacheHits=2))
finally:call(startup+['shutdown'])
(folder/'report.json').write_text(json.dumps(rows,indent=2)+'\n')
