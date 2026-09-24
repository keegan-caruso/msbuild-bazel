"""Small neutral/platform contract pair and invalidation controls."""
import json
import os
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[2];out=Path(sys.argv[1]).resolve();w=out/'source';w.mkdir(parents=True)
sdk=os.environ['RULES_MSBUILD_DOTNET_ROOT'];bazel=os.environ['RULES_MSBUILD_BAZEL']
def put(name,text):
    p=w/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
put('MODULE.bazel',f'''module(name="platform_contracts")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(root))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(sdk)},include_runtime_closure=False)
register_toolchains("//:registered")
''')
project='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>{}</Project>'
put('ref/Ref.csproj',project.format(''));put('impl/Impl.csproj',project.format(''))
put('ref/Code.cs','public static class Api { public static int Read() => throw null; }')
put('impl/Code.cs','public static class Api { public static int Read() => 7; }')
put('app/App.csproj',project.format('<ItemGroup><ProjectReference Include="../impl/Impl.csproj" SetTargetFramework="TargetFramework=net10.0-windows" /></ItemGroup>'))
put('app/Code.cs','return Api.Read()==7 ? 0 : 1;')
header='''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_assembly","msbuild_test")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
msbuild_library(name="contract",project="ref/Ref.csproj",assembly_name="Pair",srcs=["ref/Code.cs"],target_framework="CONTRACT",output_mode="reference",linux_worker=True)
msbuild_library(name="impl",project="impl/Impl.csproj",assembly_name="Pair",srcs=["impl/Code.cs"],target_framework="IMPLEMENTATION",output_mode="implementation",linux_worker=True)
msbuild_assembly(name="pair",contract=":contract",implementation=":impl")
msbuild_test(name="app",project="app/App.csproj",srcs=["app/Code.cs"],target_framework="CONSUMER",deps=[":pair"],use_apphost=False,linux_worker=True)
'''
def configure(contract,implementation,consumer='net10.0-windows'):put('BUILD.bazel',header.replace('CONTRACT',contract).replace('IMPLEMENTATION',implementation).replace('CONSUMER',consumer))
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
configure('net10.0','net10.0-windows');run('neutral-contract-platform-implementation')
reference=(w/'bazel-bin/pair.reference/Pair.dll').read_bytes()
put('impl/Code.cs','public static class Api { public static int Read() => 8; }')
row=run('implementation-edit','FAIL');assert row['compiled']==['//:impl'] and row['testsExecuted']==['//:app'],row
assert (w/'bazel-bin/pair.reference/Pair.dll').read_bytes()==reference
put('impl/Code.cs','public static class Api { public static int Read() => 7; }');run('restore')
configure('net10.0-windows','net10.0-windows');run('same-platform')
configure('net10.0-windows','net10.0');run('reverse-platform-rejected','assembly name/framework must match')
configure('net10.0-android','net10.0-windows');run('different-platform-rejected','assembly name/framework must match')
configure('net9.0','net10.0-windows');run('different-base-rejected','assembly name/framework must match')
configure('net10.0','net10.0-windows');run('recovered')
configure('net10.0','net10.0-windows','net10.0');run('neutral-consumer-paired-implementation')
put('BUILD.bazel',(w/'BUILD.bazel').read_text().replace('deps=[":pair"]','deps=[":impl"]'))
run('unpaired-platform-reference-rejected','Incompatible explicit project frameworks')
configure('net10.0','net10.0-windows')
put('app/App.csproj',(w/'app/App.csproj').read_text().replace('TargetFramework=net10.0-windows','TargetFramework=net10.0'))
run('implementation-configuration-still-validated','Configured ProjectReference disagrees with Bazel producer')
put('app/App.csproj',(w/'app/App.csproj').read_text().replace('TargetFramework=net10.0"','TargetFramework=net10.0-windows"'))
run('restore-configured-implementation')
# Implementation-private dependencies must still appear in the executable's
# runtime graph when the consumer restores against a separate public contract.
put('leaf/Leaf.csproj',project.format(''))
put('leaf/Code.cs','public static class Leaf { public static int Read() => 7; }')
put('impl/Impl.csproj',project.format('<ItemGroup><ProjectReference Include="../leaf/Leaf.csproj" /></ItemGroup>'))
put('impl/Code.cs','public static class Api { public static int Read() => Leaf.Read(); }')
configure('net10.0','net10.0-windows','net10.0')
put('BUILD.bazel',(w/'BUILD.bazel').read_text().replace('name="impl",','name="impl",deps=[":leaf"],')+'\nmsbuild_library(name="leaf",project="leaf/Leaf.csproj",srcs=["leaf/Code.cs"],target_framework="net10.0",linux_worker=True)\n')
run('implementation-private-runtime-dependency')
put('app/Code.cs','return Leaf.Read()==7 ? 0 : 1;')
run('private-runtime-api-not-compiler-visible','CS0103')
put('app/Code.cs','return Api.Read()==7 ? 0 : 1;')
run('restore-contract-consumer')
put('leaf/Code.cs','public static class Leaf { public static int Read() => 8; }')
row=run('private-runtime-body-edit','FAIL');assert row['compiled']==['//:leaf'] and row['testsExecuted']==['//:app'],row
put('leaf/Code.cs','public static class Leaf { public static int Read() => 7; }')
run('restore-private-runtime')

# A deliberate implementation compiler edge retains the paired public framework
# while making friend-visible implementation metadata available to the compiler.
put('impl/Code.cs','[assembly: System.Runtime.CompilerServices.InternalsVisibleTo("App")] public static class Api { public static int Read() => 7; internal static int Secret() => 9; }')
put('app/Code.cs','return Api.Secret()==9 ? 0 : 1;')
run('public-contract-hides-friend-member','CS0117')
put('BUILD.bazel',(w/'BUILD.bazel').read_text().replace('name="pair",','name="pair",use_implementation_reference=True,'))
run('explicit-implementation-friend-reference')
put('impl/Code.cs',(w/'impl/Code.cs').read_text().replace('Secret() => 9','Secret() => 10'))
row=run('implementation-reference-body-edit','FAIL');assert row['compiled']==['//:app','//:impl'] and row['testsExecuted']==['//:app'],row
put('impl/Code.cs',(w/'impl/Code.cs').read_text().replace('Secret() => 10','Secret() => 9'))
run('restore-implementation-reference')
