"""Exercise upstream Avalonia IDLs with pinned MicroCom through generic generation."""
import base64,hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];folder=Path(sys.argv[1]).resolve();folder.mkdir(parents=True);src=folder/'src';src.mkdir();raw=folder/'raw';raw.mkdir();sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);bazel=os.environ['RULES_MSBUILD_BAZEL'];upstream=Path(sys.argv[2]);rows=[]
def call(args,cwd=src,ok=True):
 p=subprocess.run(list(map(str,args)),cwd=cwd,capture_output=True,text=True,timeout=240)
 if ok:assert p.returncode==0,(args,(p.stdout+p.stderr)[-6000:])
 else:assert p.returncode!=0,args
 return p.stdout+p.stderr
assert call(['git','rev-parse','HEAD'],upstream).strip()=='37fbd9655cc581ff5b1c6b1fb1be4e3118c889d0'
ids=['src/Avalonia.Native/avn.idl','src/Windows/Avalonia.Win32/Win32Com/win32.idl','src/Windows/Avalonia.Win32/WinRT/winrt.idl','src/Windows/Avalonia.Win32/DirectX/directx.idl','src/Windows/Avalonia.Win32/DComposition/dcomp.idl']
project='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="MicroCom.CodeGenerator.MSBuild" Version="0.11.0" PrivateAssets="all" /></ItemGroup><ItemGroup><MicroComIdl Include="input.idl" CSharpInteropPath="$(GeneratedSource)" /></ItemGroup></Project>'
for root in [src,raw]:(root/'Generate.csproj').write_text(project)
packages=folder/'nuget';call([sdk/'dotnet','restore','-p:RestorePackagesPath='+str(packages),'-p:NuGetAudit=false'],raw)
archive=packages/'microcom.codegenerator.msbuild/0.11.0/microcom.codegenerator.msbuild.0.11.0.nupkg';digest=hashlib.sha256(archive.read_bytes()).hexdigest();assert digest=='4ecc73897f55f13dea46b100de8f7063ce28703714514073bc0462e50656db7a';shutil.copyfile(archive,src/'microcom.nupkg')
(src/'MODULE.bazel').write_text(f'''module(name="avalonia_generation")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(str(sdk))},include_runtime_closure=False)
register_toolchains("//:registered")
''')
build='''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_generate","msbuild_items","msbuild_nuget_package")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
'''+f'msbuild_nuget_package(name="microcom",package_id="MicroCom.CodeGenerator.MSBuild",version="0.11.0",archive="microcom.nupkg",archive_sha256="{digest}",content_hash="{base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()}")\n'+'''msbuild_items(name="idl",item_type="MicroComIdl",srcs=["input.idl"])
msbuild_generate(name="generate",project="Generate.csproj",target_framework="net10.0",build_deps=[":microcom"],package_private_assets={"MicroCom.CodeGenerator.MSBuild":"all"},items=[":idl"],adapter_imports=["adapter.targets"],targets=["GenerateMicroComItems"],outputs=["Interop.Generated.cs"],output_properties={"GeneratedSource":"Interop.Generated.cs"},linux_worker=True)
'''
(src/'BUILD.bazel').write_text(build)
adapter='<Project><Target Name="BindGeneratedFile" BeforeTargets="GenerateMicroComItems"><ItemGroup><MicroComIdl Update="@(MicroComIdl)"><CSharpInteropPath>$(GeneratedSource)</CSharpInteropPath></MicroComIdl></ItemGroup></Target></Project>'
(src/'adapter.targets').write_text(adapter)
startup=[bazel,'--output_base='+str(folder/'base'),'--ignore_all_rc_files'];flags=['--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE'],'--disk_cache='+str(folder/'cache'),'--strategy=MSBuildGenerate=worker','--worker_max_instances=MSBuildGenerate=1']
try:
 for index,path in enumerate(ids):
  for root in [raw,src]:shutil.copyfile(upstream/path,root/'input.idl')
  output=raw/'Interop.Generated.cs'
  if output.exists():output.unlink()
  call([sdk/'dotnet','msbuild','Generate.csproj','-t:GenerateMicroComItems','-p:RestorePackagesPath='+str(packages),'-p:GeneratedSource='+str(output)],raw)
  call(startup+['build','//:generate']+flags)
  actual=src/'bazel-bin/generate.generated/Interop.Generated.cs';assert output.read_bytes()==actual.read_bytes(),path
  assert not (src/'Interop.Generated.cs').exists()
  rows.append(dict(idl=path,sha256=hashlib.sha256(actual.read_bytes()).hexdigest(),bytes=actual.stat().st_size));print(path,'parity',flush=True)
 # Required output and source-write controls use the same real generator.
 (src/'adapter.targets').write_text(adapter.replace('$(GeneratedSource)','missing.cs'))
 failure=call(startup+['build','//:generate']+flags,ok=False);assert 'Read-only file system' in failure or 'denied' in failure,failure
 (src/'adapter.targets').write_text(adapter.replace('$(GeneratedSource)',"$([System.IO.Path]::GetDirectoryName('$(GeneratedSource)'))/other.cs"))
 failure=call(startup+['build','//:generate']+flags,ok=False);assert 'Missing declared generated output' in failure,failure
 (src/'adapter.targets').write_text(adapter);call(startup+['build','//:generate']+flags)
 call(startup+['shutdown']);relocated=folder/'relocated';shutil.copytree(src,relocated,ignore=shutil.ignore_patterns('bazel-*'));shutil.rmtree(src);shutil.rmtree(folder/'base');shutil.rmtree(raw);src=relocated
 # call's default cwd is the old path: explicitly use the relocated directory.
 startup=[bazel,'--output_base='+str(folder/'recovery'),'--output_user_root='+str(folder/'fresh-user'),'--ignore_all_rc_files']
 call(startup+['build','//:generate','--execution_log_json_file='+str(folder/'recovery.json')]+flags,src)
 text=(folder/'recovery.json').read_text();decoder=json.JSONDecoder();actions=[]
 while text.strip():
  action,end=decoder.raw_decode(text.lstrip());text=text.lstrip()[end:]
  if action.get('mnemonic')=='MSBuildGenerate':actions.append(action)
 assert len(actions)==1 and actions[0].get('cacheHit'),actions
 rows.append(dict(readOnlySources=True,missingOutputRejected=True,relocatedCacheHit=True))
finally:call(startup+['shutdown'],src)
(folder/'report.json').write_text(json.dumps(rows,indent=2)+'\n')
