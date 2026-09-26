"""Reference, custom-task, and friend-assembly sync contracts on a small real graph."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

rules=Path(__file__).resolve().parents[2]
folder=Path(sys.argv[1]).resolve();folder.mkdir(parents=True,exist_ok=False)
workspace=folder/'src';workspace.mkdir()
bazel=os.environ.get('RULES_MSBUILD_BAZEL',str(rules/'scripts/bazel-launcher.sh'))
cmd=[bazel,'--output_base='+str(folder/'base'),'--ignore_all_rc_files'];rows=[]
def put(path,text):
 p=workspace/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
def run(name,args,expected=None,error=None):
 p=subprocess.run(cmd+args,cwd=workspace,text=True,capture_output=True);output=p.stdout+p.stderr
 (folder/(name+'.log')).write_text(output)
 assert (p.returncode==0) if error is None else (p.returncode!=0 and error in output),(name,output[-7000:])
 if expected is not None:assert p.stdout.strip().splitlines()[-1]==expected,(name,p.stdout[-1000:])
 rows.append(dict(case=name,exit=p.returncode));print(name,p.returncode,flush=True)
put('MODULE.bazel','module(name="sync_roles")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(rules))+')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",global_json="//:global.json")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
for name in ['global.json','.bazelversion']:shutil.copyfile(rules/name,workspace/name)
put('Directory.Build.props','<Project><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
put('Core/Core.csproj','<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><InternalsVisibleTo Include="Friend"/></ItemGroup></Project>')
put('Core/Core.cs','public static class CoreValue { internal static int Get() => 7; }')
put('Task/Task.csproj','<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><Reference Include="$(MSBuildBinPath)/Microsoft.Build.Framework.dll" Private="false"/></ItemGroup></Project>')
put('Task/Task.cs','''using Microsoft.Build.Framework;
public class FixtureTask : ITask {
 public IBuildEngine BuildEngine {get;set;} public ITaskHost HostObject {get;set;}
 [Required] public string Output {get;set;} [Required] public string Input {get;set;}
 public bool Execute() {System.IO.File.WriteAllText(Output,"public static class Generated { public static int Value => "+System.IO.File.ReadAllText(Input)+"; }"); return true;}
}''')
logic='<Project><UsingTask TaskName="FixtureTask" AssemblyFile="$(BuildTasksLocation)"/><Target Name="Generate" BeforeTargets="CoreCompile"><FixtureTask Input="$(MSBuildThisFileDirectory)payload.txt" Output="$(IntermediateOutputPath)Generated.cs"/><ItemGroup><Compile Include="$(IntermediateOutputPath)Generated.cs"/></ItemGroup></Target></Project>'
put('App/Logic.targets',logic);put('App/payload.txt','2')
app='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><AssemblyName>Friend</AssemblyName></PropertyGroup><ItemGroup><Reference Include="Core"/></ItemGroup><Import Project="Logic.targets"/></Project>'
put('App/App.csproj',app);put('App/Program.cs','System.Console.WriteLine(CoreValue.Get()+Generated.Value);')
mapping=dict(projects={'App/App.csproj':dict(references={'Core':dict(role='compile',label=':Core_Core')},tools=[':tool'],bindings=[':task_path'],documents={'App/Logic.targets':dict(sha256=hashlib.sha256(logic.encode()).hexdigest(),targets=['Generate'],tasks=['FixtureTask'],inputs=['App/payload.txt'])})})
put('sync.json',json.dumps(mapping))
authored='''load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_tool","msbuild_file_binding")
exports_files(["global.json"])
msbuild_library(name="task",project="Task/Task.csproj",srcs=["Task/Task.cs"],target_framework="net10.0",msbuild_imports=["Directory.Build.props"])
msbuild_tool(name="tool",assembly=":task")
msbuild_file_binding(name="task_path",tool=":tool",property_name="BuildTasksLocation")
msbuild_sync(name="sync",projects=["Core/Core.csproj","App/App.csproj"],mappings="sync.json",bindings=[":task_path"])
'''
put('BUILD.bazel',authored)
try:
 run('sync',['run','//:sync'])
 put('BUILD.bazel','load(":projects.generated.bzl","app_projects")\n'+authored+'app_projects()\n')
 run('run',['run','//:App_App','--jobs=2'],expected='9')
 put('App/payload.txt','3');run('task-input-edit',['run','//:App_App','--jobs=2'],expected='10')
 task=(workspace/'Task/Task.cs').read_text();put('Task/Task.cs',task.replace('ReadAllText(Input)','ReadAllText(Input)+"+1"'))
 run('task-body-edit',['run','//:App_App','--jobs=2'],expected='11')
 put('Core/Core.cs','public static class CoreValue { internal static int Get() => 8; }')
 run('friend-body-edit',['run','//:App_App','--jobs=2'],expected='12')
 # Disposable signing keys are generated outside the application workspace.
 sdk=Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT',rules/'.tools/dotnet'))
 keytool=folder/'keytool';keytool.mkdir()
 (keytool/'Key.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup></Project>')
 (keytool/'Program.cs').write_text('using System; using System.IO; using System.Security.Cryptography; using var rsa=new RSACryptoServiceProvider(2048); var key=rsa.ExportCspBlob(true); BitConverter.GetBytes(0x2400).CopyTo(key,4); File.WriteAllBytes(args[0],key); var blob=rsa.ExportCspBlob(false); BitConverter.GetBytes(0x2400).CopyTo(blob,4); using var stream=new MemoryStream(); using var writer=new BinaryWriter(stream); writer.Write(0x2400);writer.Write(0x8004);writer.Write(blob.Length);writer.Write(blob);File.WriteAllText(args[1],Convert.ToHexString(stream.ToArray()));')
 subprocess.run([str(sdk/'dotnet'),'build',str(keytool/'Key.csproj'),'-c','Release'],check=True,stdout=subprocess.DEVNULL)
 for key in ['key','wrong']:
  subprocess.run([str(sdk/'dotnet'),str(keytool/'bin/Release/net10.0/Key.dll'),str(folder/(key+'.snk')),str(folder/(key+'.pub'))],check=True)
 public=(folder/'key.pub').read_text()
 sign='<PropertyGroup><SignAssembly>true</SignAssembly><AssemblyOriginatorKeyFile>key.snk</AssemblyOriginatorKeyFile></PropertyGroup>'
 core=(workspace/'Core/Core.csproj').read_text()
 put('Core/Core.csproj',core.replace('Include="Friend"','Include="Friend" Key="'+public+'"').replace('</Project>',sign+'</Project>'))
 put('App/App.csproj',app.replace('</Project>',sign+'</Project>'))
 for project in ['Core','App']:shutil.copyfile(folder/'key.snk',workspace/project/'key.snk')
 run('sync-signed',['run','//:sync'])
 run('signed-friend',['run','//:App_App','--jobs=2'],expected='12')
 shutil.copyfile(folder/'wrong.snk',workspace/'App/key.snk')
 run('wrong-key-rejected',['build','//:App_App','--jobs=2'],error='CS0281')
 put('Core/Core.csproj',core)
 put('App/App.csproj',app.replace('<AssemblyName>Friend</AssemblyName>','<AssemblyName>Stranger</AssemblyName>'))
 run('resync-stranger',['run','//:sync'])
 run('nonfriend-rejected',['build','//:App_App','--jobs=2'],error='CS0117')
 put('App/Logic.targets',logic+'\n')
 run('contract-drift',['run','//:sync'],error='contract changed')
finally:
 subprocess.run(cmd+['shutdown'],cwd=workspace,check=True)
 (folder/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
