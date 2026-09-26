"""Synchronized reference/implementation pairing and enforced artifact selection."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

rules=Path(__file__).resolve().parents[2];folder=Path(sys.argv[1]).resolve();folder.mkdir(parents=True,exist_ok=False)
workspace=folder/'src';workspace.mkdir();rows=[]
bazel=os.environ.get('RULES_MSBUILD_BAZEL',str(rules/'scripts/bazel-launcher.sh'));cmd=[bazel,'--output_base='+str(folder/'base'),'--ignore_all_rc_files']
def put(path,text):
 p=workspace/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
def run(name,args,expected=None,error=None):
 p=subprocess.run(cmd+args,cwd=workspace,text=True,capture_output=True);output=p.stdout+p.stderr;(folder/(name+'.log')).write_text(output)
 assert (p.returncode==0) if error is None else (p.returncode!=0 and error in output),(name,output[-5000:])
 if expected is not None:assert p.stdout.strip().splitlines()[-1]==expected
 rows.append(dict(case=name,exit=p.returncode));print(name,p.returncode,flush=True)
put('MODULE.bazel','module(name="sync_implementation")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(rules))+')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",global_json="//:global.json")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
for f in ['global.json','.bazelversion']:shutil.copyfile(rules/f,workspace/f)
put('Directory.Build.props','<Project><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
for directory in ['Contract','Impl']:
 put(directory+'/'+directory+'.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><AssemblyName>Pair</AssemblyName></PropertyGroup></Project>')
put('Contract/Value.cs','public static class Value { public static int Get() => throw null; }')
put('Impl/Value.cs','public static class Value { public static int Get() => 7; public static int Extra() => 9; }')
put('App/App.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Impl/Impl.csproj" SkipUseReferenceAssembly="true"/></ItemGroup></Project>')
put('App/Program.cs','System.Console.WriteLine(Value.Extra());')
mapping={'projects':{'Contract/Contract.csproj':{'outputMode':'reference'},'Impl/Impl.csproj':{'outputMode':'implementation'},'App/App.csproj':{'projectReferences':{'Impl/Impl.csproj':{'role':'compile','label':':implementation_pair'}}}}}
put('sync.json',json.dumps(mapping))
authored='''load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_assembly")
exports_files(["global.json"])
msbuild_sync(name="sync",projects=["Contract/Contract.csproj","Impl/Impl.csproj","App/App.csproj"],mappings="sync.json")
msbuild_assembly(name="implementation_pair",contract=":Contract_Contract_net10_0",implementation=":Impl_Impl_net10_0",use_implementation_reference=True)
msbuild_assembly(name="contract_pair",contract=":Contract_Contract_net10_0",implementation=":Impl_Impl_net10_0")
'''
put('BUILD.bazel',authored)
try:
 run('sync',['run','//:sync'])
 put('BUILD.bazel','load(":projects.generated.bzl","app_projects")\n'+authored+'app_projects()\n')
 run('implementation',['run','//:App_App','--jobs=2'],expected='9')
 put('Impl/Value.cs','public static class Value { public static int Get() => 7; public static int Extra() => 10; }')
 run('implementation-body-edit',['run','//:App_App','--jobs=2'],expected='10')
 mapping['projects']['App/App.csproj']['projectReferences']['Impl/Impl.csproj']['label']=':contract_pair';put('sync.json',json.dumps(mapping))
 run('resync-contract',['run','//:sync'])
 run('wrong-artifact-rejected',['build','//:App_App','--jobs=2'],error='SkipUseReferenceAssembly requires')
finally:
 subprocess.run(cmd+['shutdown'],cwd=workspace,check=True)
 (folder/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
