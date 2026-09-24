"""Direct-only compiler inputs retain the transitive runtime closure."""
import json
import os
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[2];out=Path(sys.argv[1]).resolve();w=out/'source';w.mkdir(parents=True)
sdk=os.environ['RULES_MSBUILD_DOTNET_ROOT'];bazel=os.environ['RULES_MSBUILD_BAZEL']
def put(name,text):
    p=w/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
put('MODULE.bazel',f'''module(name="direct_references")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(root))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(sdk)},include_runtime_closure=False)
register_toolchains("//:registered")
''')
project='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>{}</Project>'
put('leaf/Leaf.csproj',project.format(''));put('leaf/Code.cs','public static class Leaf { public static int Value => 7; }')
put('middle/Middle.csproj',project.format('<ItemGroup><ProjectReference Include="../leaf/Leaf.csproj" /></ItemGroup>'))
put('middle/Code.cs','public static class Middle { public static int Read() => Leaf.Value; }')
header='''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_test")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
msbuild_library(name="leaf",project="leaf/Leaf.csproj",srcs=["leaf/Code.cs"],target_framework="net10.0",linux_worker=True)
msbuild_library(name="middle",project="middle/Middle.csproj",srcs=["middle/Code.cs"],deps=[":leaf"],target_framework="net10.0",linux_worker=True)
'''
def configure(transitive=True,leaf=False,body='return Middle.Read()==7 && Leaf.Value==7 ? 0 : 1;'):
    refs='<ProjectReference Include="../middle/Middle.csproj" />'+('<ProjectReference Include="../leaf/Leaf.csproj" />' if leaf else '')
    put('direct/Direct.csproj',project.format('<ItemGroup>'+refs+'</ItemGroup>'))
    put('direct/Code.cs','public static class Direct { public static int Read() { '+body+' } }')
    put('app/App.csproj',project.format('<ItemGroup><ProjectReference Include="../direct/Direct.csproj" /></ItemGroup>'))
    put('app/Code.cs','return Direct.Read();')
    put('BUILD.bazel',header+'msbuild_library(name="direct",project="direct/Direct.csproj",srcs=["direct/Code.cs"],target_framework="net10.0",deps='+str([':middle']+([':leaf'] if leaf else []))+',transitive_compile_references='+str(transitive)+',linux_worker=True)\nmsbuild_test(name="app",project="app/App.csproj",srcs=["app/Code.cs"],deps=[":direct"],target_framework="net10.0",use_apphost=False,linux_worker=True)\n')
records=[]
def run(name,error=None):
    execution=out/(name+'.execution.json')
    with (out/(name+'.log')).open('w') as log:
        result=subprocess.run([bazel,'--batch','--host_jvm_args=-Xmx768m','--output_base='+str(out/'base'),'--ignore_all_rc_files','test','//:app','--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--disk_cache='+str(out/'cache'),'--test_output=errors','--execution_log_json_file='+str(execution)],cwd=w,stdout=log,stderr=subprocess.STDOUT,timeout=240)
    text=(out/(name+'.log')).read_text()
    assert (result.returncode==0)==(error is None),(name,text[-6000:])
    if error:assert error in text,(name,text[-6000:])
    rows=[];data=execution.read_text() if execution.exists() else '';decoder=json.JSONDecoder()
    while data.strip():
        row,end=decoder.raw_decode(data.lstrip());data=data.lstrip()[end:];rows.append(row)
    record=dict(case=name,exitCode=result.returncode,compiled=sorted(r['targetLabel'] for r in rows if r.get('mnemonic')=='MSBuildAssembly' and not r.get('cacheHit')),testsExecuted=sorted({r['targetLabel'] for r in rows if r.get('mnemonic')=='TestRunner' and not r.get('cacheHit')}))
    records.append(record);(out/'report.json').write_text(json.dumps(records,indent=2)+'\n');print(record,flush=True);return record
configure();run('default-transitive')
configure(False);run('missing-direct-reference','CS0103')
configure(False,True);run('explicit-direct-reference')
configure(False,False,'return Middle.Read()==7 ? 0 : 1;');run('runtime-still-transitive')
configure();run('restore-default')
put('BUILD.bazel',(w/'BUILD.bazel').read_text().replace('use_apphost=False','use_apphost=False,transitive_compile_references=False'))
run('executable-direct-only-rejected','supported only for libraries')
configure();run('restore-after-rejection')
