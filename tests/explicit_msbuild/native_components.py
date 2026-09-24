"""Declared native compiler/task/header closure -> generated P/Invoke runtime data.

Requires gcc on the fixture host to acquire tools; actions use staged explicit tools.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
SDK=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);BAZEL=os.environ['RULES_MSBUILD_BAZEL']
folder=Path(sys.argv[1]).resolve();folder.mkdir(parents=True);workspace=folder/'source';workspace.mkdir()
def put(path,text):
    target=workspace/path;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
put('MODULE.bazel',f'''module(name="native_components")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(str(SDK))},include_runtime_closure=False)
register_toolchains("//:registered")
''')
compiler=Path(shutil.which('gcc')).resolve()
tools={'gcc':compiler,'cc1':Path(subprocess.check_output([compiler,'-print-prog-name=cc1'],text=True).strip()),'as':Path(shutil.which('as')).resolve(),'ld':Path(shutil.which('ld')).resolve()}
for name,path in tools.items():
    dest=workspace/'native-tools'/name;dest.parent.mkdir(exist_ok=True);shutil.copy2(path,dest)
(folder/'tool-identities.json').write_text(json.dumps({n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in tools.items()},indent=2))
build='''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_test","msbuild_tool","msbuild_file_binding","msbuild_native_tool","msbuild_layout","msbuild_generate")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
msbuild_layout(name="compiler_tree",paths={"native-tools/gcc":"gcc","native-tools/cc1":"cc1","native-tools/as":"as","native-tools/ld":"ld"})
msbuild_native_tool(name="compiler",layout=":compiler_tree",entry_point="gcc")
msbuild_file_binding(name="compiler_binding",tool=":compiler",property_name="NativeCompiler")
msbuild_library(name="task",project="task/Task.csproj",srcs=["task/Code.cs"],target_framework="net10.0",linux_worker=True)
msbuild_tool(name="task_tool",assembly=":task")
msbuild_file_binding(name="task_binding",tool=":task_tool",property_name="NativeTask")
msbuild_layout(name="inputs",paths={"shim/shim.c":"shim.c","shim/value.h":"value.h"})
msbuild_generate(name="shim",project="shim/Generate.csproj",target_framework="net10.0",tools=[":compiler",":task_tool"],bindings=[":compiler_binding",":task_binding"],layout_bindings={":inputs":"NativeInputs"},targets=["Native"],outputs=["libfixture.so"],output_properties={"NativeOutput":"libfixture.so"},linux_worker=True)
msbuild_test(name="consumer",project="app/App.csproj",srcs=["app/Code.cs"],target_framework="net10.0",data_paths={":shim":"libfixture.so"},use_apphost=False,linux_worker=True)
'''
project='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>{}</Project>'
put('BUILD.bazel',build)
put('task/Task.csproj',project.format('<ItemGroup><Reference Include="$(MSBuildBinPath)/Microsoft.Build.Framework.dll" Private="false"/></ItemGroup>'))
put('task/Code.cs','''using Microsoft.Build.Framework;
public sealed class Native : ITask {
 public IBuildEngine BuildEngine { get; set; }=null!;
 public ITaskHost HostObject { get; set; }=null!;
 [Required] public string Compiler { get; set; }=null!;
 [Required] public string Inputs { get; set; }=null!;
 [Required] public string Output { get; set; }=null!;
 public bool Execute() {
  var root=System.IO.Path.GetDirectoryName(Compiler)!;
  foreach(var tool in new[]{"gcc","cc1","as","ld"})
   if(!System.IO.File.Exists(System.IO.Path.Combine(root,tool))) throw new System.Exception("Missing declared native closure: "+tool);
  var process=new System.Diagnostics.ProcessStartInfo(Compiler) { RedirectStandardOutput=true, RedirectStandardError=true };
  foreach(var arg in new[]{"-B"+root+"/","-shared","-fPIC","-fno-use-linker-plugin","-nostdlib","-nostdinc","-o",Output,System.IO.Path.Combine(Inputs,"shim.c")})process.ArgumentList.Add(arg);
  process.Environment["GCC_EXEC_PREFIX"]=root+"/";
  using var child=System.Diagnostics.Process.Start(process)!;var output=child.StandardError.ReadToEnd();child.WaitForExit();if(child.ExitCode!=0)throw new System.Exception(output);return true;
 }
}
''')
put('shim/Generate.csproj',project.format('<UsingTask TaskName="Native" AssemblyFile="$(NativeTask)"/><Target Name="Native"><Native Compiler="$(NativeCompiler)" Inputs="$(NativeInputs)" Output="$(NativeOutput)"/></Target>'))
put('shim/shim.c','#include "value.h"\nint fixture_value(void) { return VALUE; }\n');put('shim/value.h','#define VALUE 7\n')
put('app/App.csproj',project.format(''))
put('app/Code.cs','''using System.Runtime.InteropServices;
System.Console.WriteLine(Native.Value());return Native.Value()==7 ? 0 : 1;
static class Native { [DllImport("fixture",EntryPoint="fixture_value")] public static extern int Value(); }
''')
startup=[BAZEL,'--host_jvm_args=-Xmx768m','--output_base='+str(folder/'base'),'--ignore_all_rc_files'];records=[]
def run(case,error=None,force=False):
    log=folder/(case+'.execution.json')
    p=subprocess.run(startup+['test','//:consumer','--test_output=all','--jobs=2','--strategy=MSBuildAssembly=worker','--strategy=MSBuildGenerate=worker','--worker_max_instances=MSBuildAssembly=1','--worker_max_instances=MSBuildGenerate=1','--disk_cache='+str(folder/'cache'),'--execution_log_json_file='+str(log)]+(['--nocache_test_results'] if force else []),cwd=workspace,capture_output=True,text=True,timeout=240)
    output=p.stdout+p.stderr;(folder/(case+'.log')).write_text(output)
    assert (p.returncode==0)==(error is None),(case,output[-7000:])
    if error:assert error in output,(case,error,output[-5000:])
    rows=[];text=log.read_text();decoder=json.JSONDecoder()
    while text.strip():
        row,end=decoder.raw_decode(text.lstrip());text=text.lstrip()[end:];rows.append(row)
    ran=sorted(r['targetLabel'] for r in rows if r.get('mnemonic') in ['MSBuildAssembly','MSBuildGenerate'] and not r.get('cacheHit'))
    record={'case':case,'exitCode':p.returncode,'built':ran,'testExecuted':any(r.get('mnemonic')=='TestRunner' and not r.get('cacheHit') for r in rows)};records.append(record);print(json.dumps(record),flush=True)
    (folder/'report.json').write_text(json.dumps(records,indent=2)+'\n');return record
try:
    run('native-pinvoke')
    put('shim/value.h','#define VALUE 8\n');row=run('header-mutation',error='FAIL');assert row['built']==['//:shim'],row
    put('shim/value.h','#define VALUE 7\n');run('header-recovered')
    # A changed declared executable reruns generation, even when its output is unchanged.
    path=workspace/'native-tools/gcc';path.write_bytes(path.read_bytes()+b'\0fixture-mutation');row=run('native-tool-mutation');assert '//:shim' in row['built'] and '//:consumer' not in row['built'],row
    put('BUILD.bazel',build.replace(',"native-tools/cc1":"cc1"',''));run('missing-tool-closure',error='Missing declared native closure')
    put('BUILD.bazel',build.replace('entry_point="gcc"','entry_point="missing"'));run('missing-native-entry',error='Missing build tool entry')
    put('BUILD.bazel',build);run('recovered')
    subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
    relocated=folder/'relocated';shutil.copytree(workspace,relocated,ignore=shutil.ignore_patterns('bazel-*'));shutil.rmtree(workspace);shutil.rmtree(folder/'base');workspace=relocated
    startup=[BAZEL,'--host_jvm_args=-Xmx768m','--output_base='+str(folder/'fresh-base'),'--ignore_all_rc_files']
    row=run('producer-deleted-native-recovery',force=True);assert row['built']==[] and row['testExecuted'],row
finally:subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
