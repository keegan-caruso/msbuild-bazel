"""Pinned NBGV parity oracle: capture once, compile without Git through a late adapter.

The capture/adapter writer here is test scaffolding, not a production status bridge.
"""
import base64,hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parents[2];folder=Path(sys.argv[1]).resolve();folder.mkdir(parents=True)
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);bazel=os.environ['RULES_MSBUILD_BAZEL'];raw=folder/'raw';raw.mkdir();workspace=folder/'src';workspace.mkdir();rows=[]
version='3.10.94';archive_hash='a56dde9219f9a0743bba1f66f8c4dbf36e5a6e8dbb22cbe8eb5c8efbbc144b6e';packages=folder/'nuget'
project='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><NBGV_EmitThisAssemblyClass>true</NBGV_EmitThisAssemblyClass><NBGV_ThisAssemblyIncludesPackageVersion>true</NBGV_ThisAssemblyIncludesPackageVersion><NBGV_SetCloudBuildVersionVars>false</NBGV_SetCloudBuildVersionVars></PropertyGroup><ItemGroup><PackageReference Include="Nerdbank.GitVersioning" Version="3.10.94" PrivateAssets="all" /></ItemGroup></Project>'
(raw/'App.csproj').write_text(project)
(raw/'Program.cs').write_text('System.Console.WriteLine(ThisAssembly.AssemblyInformationalVersion); System.Console.WriteLine(ThisAssembly.AssemblyVersion); System.Console.WriteLine(ThisAssembly.NuGetPackageVersion);')
(raw/'version.json').write_text(json.dumps({'version':'1.2-beta','publicReleaseRefSpec':['^refs/heads/main$']}));(raw/'.gitignore').write_text('bin/\nobj/\n')
def call(cmd,cwd=None):
 if cwd is None:cwd=raw
 r=subprocess.run(list(map(str,cmd)),cwd=cwd,capture_output=True,text=True,timeout=240)
 assert r.returncode==0,(cmd,(r.stdout+r.stderr)[-5000:])
 return r.stdout
for cmd in [['git','init','-b','main'],['git','config','user.name','Fixture'],['git','config','user.email','fixture@example.invalid'],['git','add','.'],['git','commit','-m','Initial'],['git','commit','--allow-empty','-m','Second']]:call(cmd)
props=['-p:RestorePackagesPath='+str(packages),'-p:NuGetAudit=false','-p:ProduceReferenceAssembly=true','-p:DebugType=portable','-p:Configuration=Release']
call([sdk/'dotnet','build',*props])
archive=packages/'nerdbank.gitversioning'/version/('nerdbank.gitversioning.'+version+'.nupkg');assert hashlib.sha256(archive.read_bytes()).hexdigest()==archive_hash
assets=json.loads((raw/'obj/project.assets.json').read_text());assert list(assets['libraries'])==['Nerdbank.GitVersioning/'+version],assets['libraries'].keys()
for name in ('App.csproj','Program.cs','version.json'):shutil.copyfile(raw/name,workspace/name)
shutil.copyfile(archive,workspace/'nbgv.nupkg')
(workspace/'MODULE.bazel').write_text(f'''module(name="nbgv_parity")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(str(sdk))},include_runtime_closure=False)
register_toolchains("//:registered")
''')
(workspace/'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_binary","msbuild_nuget_package")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
'''+f'msbuild_nuget_package(name="nbgv",package_id="Nerdbank.GitVersioning",version="{version}",archive="nbgv.nupkg",archive_sha256="{archive_hash}",content_hash="{base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()}")\n'+'''msbuild_binary(name="App",project="App.csproj",target_framework="net10.0",srcs=["Program.cs"],build_deps=[":nbgv"],package_private_assets={"Nerdbank.GitVersioning":"all"},adapter_imports=["version.targets"],msbuild_imports=["version.json"],linux_worker=True)
''')
base=folder/'base';startup=[bazel,'--output_base='+str(base),'--ignore_all_rc_files'];flags=['--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE'],'--disk_cache='+str(folder/'cache'),'--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1']
def escape(value):
 for a,b in [('%','%25'),('$','%24'),('@','%40'),(';','%3B'),("'",'%27'),('(','%28'),(')','%29'),('*','%2A'),('?','%3F')]:value=value.replace(a,b)
 return value

def check(name,extra=[]):
 call([sdk/'dotnet','build',*props,*extra])
 expected=call([sdk/'dotnet',raw/'bin/Release/net10.0/App.dll']).strip()
 capture=json.loads(call([sdk/'dotnet','msbuild','App.csproj','-t:GetBuildVersion','-getItem:NBGV_PropertyItems',*props,*extra]))['Items']['NBGV_PropertyItems']
 manifest=[dict(name=r['Identity'],value=r.get('Value',''),honorPresetValue=r['HonorPresetValue']) for r in capture]
 (folder/(name+'.manifest.json')).write_text(json.dumps(manifest,indent=2)+'\n')
 xml=ET.Element('Project');target=ET.SubElement(xml,'Target',Name='InvokeGetBuildVersionTask');items=ET.SubElement(target,'ItemGroup');ET.SubElement(items,'NBGV_PropertyItems',Remove='@(NBGV_PropertyItems)');ET.SubElement(items,'CloudBuildVersionVars',Remove='@(CloudBuildVersionVars)')
 for r in manifest:
  item=ET.SubElement(items,'NBGV_PropertyItems',Include=escape(r['name']));ET.SubElement(item,'Value').text=escape(r['value']);ET.SubElement(item,'HonorPresetValue').text=r['honorPresetValue']
 for target_name in ('SetCloudBuildVersionVars','SetCloudBuildNumberWithVersion'):ET.SubElement(xml,'Target',Name=target_name)
 ET.ElementTree(xml).write(workspace/'version.targets',encoding='unicode')
 for file in ('Program.cs','version.json'):shutil.copyfile(raw/file,workspace/file)
 output=call(startup+['run','//:App','--execution_log_json_file='+str(folder/(name+'.execution.json'))]+flags,workspace).strip()
 assert output==expected,(name,output,expected)
 rawref=hashlib.sha256((raw/'obj/Release/net10.0/ref/App.dll').read_bytes()).hexdigest();bzref=hashlib.sha256((workspace/'bazel-bin/App.reference/App.dll').read_bytes()).hexdigest()
 assert rawref==bzref,(name,rawref,bzref)
 rows.append(dict(case=name,output=output,referenceHash=rawref,properties=len(manifest),gitVisibleToCompilation=False));print(name,'parity',flush=True)
try:
 check('initial')
 check('unchanged')
 call(['git','commit','--allow-empty','-m','Third']);check('new-commit')
 call(['git','checkout','-b','feature']);check('branch-switch')
 check('public-release',['-p:PublicRelease=true'])
 (raw/'version.json').write_text(json.dumps({'version':'2.1-beta','publicReleaseRefSpec':['^refs/heads/main$']}));check('policy-edit')
 # Prove inherited configuration is calculated upstream, not flattened by a homegrown version algorithm.
 (raw/'nested').mkdir();shutil.move(raw/'App.csproj',raw/'nested/App.csproj');shutil.move(raw/'Program.cs',raw/'nested/Program.cs')
 (raw/'nested/version.json').write_text('{"inherit":true,"versionHeightOffset":10}')
 oldraw=raw;raw=raw/'nested';check('inherited-policy')
 raw=oldraw
 call(startup+['shutdown'],workspace)
 relocated=folder/'relocated';shutil.copytree(workspace,relocated,ignore=shutil.ignore_patterns('bazel-*'));shutil.rmtree(workspace);shutil.rmtree(base);shutil.rmtree(raw);workspace=relocated
 startup=[bazel,'--output_base='+str(folder/'recovery'),'--output_user_root='+str(folder/'fresh-user'),'--ignore_all_rc_files']
 output=call(startup+['run','//:App','--execution_log_json_file='+str(folder/'recovery.execution.json')]+flags,workspace).strip();assert output==rows[-1]['output']
 text=(folder/'recovery.execution.json').read_text();decoder=json.JSONDecoder();actions=[]
 while text.strip():
  r,end=decoder.raw_decode(text.lstrip());text=text.lstrip()[end:]
  if r.get('mnemonic')=='MSBuildAssembly':actions.append(r)
 assert len(actions)==1 and actions[0].get('cacheHit'),actions
 rows.append(dict(case='deleted-git-producer-cache-recovery',cacheHit=True));print('deleted-git-producer-cache-recovery pass',flush=True)
finally:
 call(startup+['shutdown'],workspace)
(folder/'report.json').write_text(json.dumps(rows,indent=2)+'\n')
