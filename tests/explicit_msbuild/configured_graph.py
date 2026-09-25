"""Raw MSBuild and configured inventory controls for a mixed-framework diamond."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('output',type=Path)
p.add_argument('--executor')
a=p.parse_args()
root=Path(__file__).resolve().parents[2];out=a.output.resolve();out.mkdir(parents=True)
source=out/'source';source.mkdir();sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
def put(name,text):
 path=source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text)
put('global.json',json.dumps({'sdk':{'version':'10.0.400','rollForward':'disable'}}))
put('Directory.Build.props','<Project><PropertyGroup><ProduceReferenceAssembly>true</ProduceReferenceAssembly><NuGetAudit>false</NuGetAudit></PropertyGroup></Project>')
put('Directory.Build.targets','''<Project><Target Name="RecordReferences" AfterTargets="ResolveReferences"><WriteLinesToFile File="$(IntermediateOutputPath)selected-refs.txt" Lines="@(ReferencePath->'%(Filename)|%(MSBuildSourceProjectFile)|%(FullPath)')" Overwrite="true" /></Target></Project>''')
put('Core/Core.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFrameworks>netstandard2.1;net10.0</TargetFrameworks></PropertyGroup></Project>')
put('Core/Api.cs','''public static class Api {
public static int Value() {
#if NET10_0
return 10;
#else
return 2;
#endif
}
}
''')
put('Helper/Helper.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>netstandard2.1</TargetFramework></PropertyGroup><ItemGroup><ProjectReference Include="../Core/Core.csproj"/></ItemGroup></Project>')
put('Helper/Helper.cs','public static class Helper { public static int Value() => Api.Value(); }')
put('App/App.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Core/Core.csproj"/><ProjectReference Include="../Helper/Helper.csproj"/></ItemGroup></Project>')
put('App/Program.cs','System.Console.WriteLine($"{Api.Value()}:{Helper.Value()}"); return Api.Value()==10 && Helper.Value()==10 ? 0 : 1;')
config=dict(entries=['App/App.csproj'],framework='net10.0',properties={'ProduceReferenceAssembly':'true','NuGetAudit':'false'})
(out/'config.json').write_text(json.dumps(config))
with (out/'raw-build.log').open('w') as log:
 subprocess.run([sdk/'dotnet','build',source/'App/App.csproj','-c','Release','-p:RestorePackagesPath='+str(out/'nuget')],cwd=source,stdout=log,stderr=subprocess.STDOUT,check=True)
raw=subprocess.check_output([sdk/'dotnet',source/'App/bin/Release/net10.0/App.dll'],text=True).strip();assert raw=='10:10',raw
app_refs=(source/'App/obj/Release/net10.0/selected-refs.txt').read_text().splitlines()
helper_refs=(source/'Helper/obj/Release/netstandard2.1/selected-refs.txt').read_text().splitlines()
assert len([r for r in app_refs if r.startswith('Core|')])==1
assert 'net10.0' in next(r for r in app_refs if r.startswith('Core|'))
assert 'netstandard2.1' in next(r for r in helper_refs if r.startswith('Core|'))
probe=out/'probe';probe.mkdir()
shutil.copyfile(root/'tests/explicit_msbuild/oss/Inventory.cs.txt',probe/'Program.cs')
shutil.copyfile(root/'tests/explicit_msbuild/oss/Inventory.csproj.txt',probe/'Inventory.csproj')
subprocess.run([sdk/'dotnet','build',probe/'Inventory.csproj','-c','Release'],check=True)
subprocess.run([sdk/'dotnet',probe/'bin/Release/net10.0/Inventory.dll',source,out/'config.json',out/'inventory.json'],check=True)
rows=json.loads((out/'inventory.json').read_text());by={r['id']:r for r in rows}
assert len(rows)==4,[(r['project'],r['globalProperties']) for r in rows]
for row in rows:
 if row['project']=='App/App.csproj':assert {by[r['node']]['framework'] for r in row['references']}=={'net10.0','netstandard2.1'}
 if row['project']=='Helper/Helper.csproj':assert {by[r['node']]['framework'] for r in row['references']}=={'netstandard2.1'}
subprocess.run([sys.executable,root/'tests/explicit_msbuild/oss/prepare.py',out,root],check=True)
(out/'raw-control.json').write_text(json.dumps(dict(output=raw,appCoreReference=next(r for r in app_refs if r.startswith('Core|')),helperCoreReference=next(r for r in helper_refs if r.startswith('Core|')),nodes=len(rows)),indent=2)+'\n')
print('Raw diamond and configured inventory passed',flush=True)

if a.executor:
 from remote_support import RemoteFixture
 labels=json.loads((out/'labels.json').read_text())
 core={r['framework']:labels[r['id']] for r in rows if r['project']=='Core/Core.csproj'}
 workspace=out/'bazel'
 build=workspace/'BUILD.bazel'
 lines=build.read_text().splitlines()
 lines=[line for line in lines if not line.startswith(('load("@rules_msbuild//msbuild:toolchain','msbuild_toolchain(','toolchain('))]
 lines=[line.replace('"msbuild_library","msbuild_binary",','"msbuild_library","msbuild_binary","msbuild_test",').replace('linux_worker=True','linux_worker=True,allow_remote_execution=True') for line in lines]
 lines=[line.replace('msbuild_binary(name="App",','msbuild_test(name="App",') if line.startswith('msbuild_binary(name="App",') else line for line in lines]
 original='\n'.join(lines)+'\n'
 build.write_text(original)
 f=RemoteFixture(out/'remote',a.executor,workspace,instance='configured-diamond/'+out.name);f.sdk()
 try:
  expected=[('MSBuildAssembly','//:'+label) for label in labels.values()]
  f.run('ambiguous-diamond',['//:App'],expected,error='Conflicting runtime/input destination',tests=[])
  build.write_text(original.replace('msbuild_test(name="App",','msbuild_test(name="App",assembly_selections=[":'+core['net10.0']+'"],'))
  f.run('selected-diamond',['//:App'],[('MSBuildAssembly','//:App')],tests=['//:App'])
  f.run('noop',['//:App'],[],tests=[])
  app_runtime=workspace/'bazel-bin/App.runtime'
  assert 'Core/1.0.0' in json.loads((app_runtime/'App.deps.json').read_text())['libraries']
  assert raw in (workspace/'bazel-testlogs/App/test.log').read_text()
  api=workspace/'Core/Api.cs';original_api=api.read_text()
  reference=workspace/('bazel-bin/'+core['net10.0']+'.reference/Core.dll')
  before=hashlib.sha256(reference.read_bytes()).hexdigest()
  api.write_text(original_api.replace('return 10;', 'return 11;'))
  f.run('body-edit',['//:App'],[('MSBuildAssembly','//:'+label) for label in core.values()],tests=['//:App'],error='FAIL')
  assert hashlib.sha256(reference.read_bytes()).hexdigest()==before
  api.write_text(original_api)
  f.run('body-restored',['//:App'],[],tests=[])
  api.write_text(original_api.replace('public static class Api {','public static class Api { public static int Added() => 42;'))
  f.run('api-edit',['//:App'],expected,tests=['//:App'])
  api.write_text(original_api)
  f.run('api-restored',['//:App'],[],tests=[])
  core_project=workspace/'Core/Core.csproj';original_project=core_project.read_text()
  core_project.write_text(original_project.replace('</PropertyGroup>', '<AssemblyVersion Condition="\'$(TargetFramework)\'==\'net10.0\'">2.0.0.0</AssemblyVersion></PropertyGroup>'))
  f.run('identity-mismatch',['//:App'],[('MSBuildAssembly','//:'+label) for label in core.values()]+[('MSBuildAssembly','//:App')],tests=[],error='Selected assembly identity differs')
  core_project.write_text(original_project)
  f.run('identity-restored',['//:App'],[],tests=[])
  f.shutdown();f.base=out/'fresh-base'
  actions=f.run('fresh-recovery',['//:App'],[],tests=[],downloads='toplevel')
  assert actions and all(x['cacheHit'] for x in actions)

 finally:
  if 'original_api' in locals():api.write_text(original_api)
  if 'original_project' in locals():core_project.write_text(original_project)
  f.shutdown()

# The same selected graph must survive persistent-worker input remapping.
if a.executor:
 base=out/'worker-base';records=[]
 def worker(case,error=None):
  execution=out/(case+'.execution.json')
  result=subprocess.run([f.bazel,'--output_base='+str(base),'--ignore_all_rc_files','test','//:App','--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--disk_cache=','--test_output=errors','--execution_log_json_file='+str(execution)],cwd=workspace,text=True,capture_output=True,timeout=240)
  output=result.stdout+result.stderr;(out/(case+'.log')).write_text(output)
  assert (result.returncode!=0)==bool(error),(case,output[-3000:])
  if error:assert error in output,(case,output[-3000:])
  actions=[];data=execution.read_text().strip();decoder=json.JSONDecoder()
  while data:
   row,end=decoder.raw_decode(data);data=data[end:].lstrip()
   if row.get('mnemonic')=='MSBuildAssembly':actions.append(row)
  assert all(row['runner']=='worker' for row in actions),actions
  records.append(dict(case=case,exitCode=result.returncode,assemblies=len(actions)))
  (out/'worker-control.json').write_text(json.dumps(records,indent=2)+'\n')
  print(records[-1],flush=True)
 try:
  worker('worker-selected')
  worker('worker-noop')
  core_project.write_text(original_project.replace('</PropertyGroup>', '<AssemblyVersion Condition="\'$(TargetFramework)\'==\'net10.0\'">2.0.0.0</AssemblyVersion></PropertyGroup>'))
  worker('worker-identity-mismatch','Selected assembly identity differs')
 finally:
  core_project.write_text(original_project)
  subprocess.run([f.bazel,'--output_base='+str(base),'shutdown'],cwd=workspace,check=True)
