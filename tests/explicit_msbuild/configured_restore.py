"""Restore metadata keeps multiple framework configurations of one project distinct."""
import json
import os
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[2];out=Path(sys.argv[1]).resolve();w=out/'source';w.mkdir(parents=True)
sdk=os.environ['RULES_MSBUILD_DOTNET_ROOT'];bazel=os.environ['RULES_MSBUILD_BAZEL']
def put(name,text):
    p=w/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
put('MODULE.bazel',f'''module(name="configured_restore")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(root))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(sdk)},include_runtime_closure=False)
register_toolchains("//:registered")
''')
project='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>FRAMEWORK</TargetFramework></PropertyGroup>REFERENCES</Project>'
put('shared/Shared.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks><AssemblyName Condition="$(TargetFramework)==net10.0">SharedNeutral</AssemblyName><AssemblyName Condition="$(TargetFramework)==net10.0-windows">SharedPlatform</AssemblyName></PropertyGroup></Project>')
source='public static class SharedApi { public static int Read() {\n#if WINDOWS\nreturn 11;\n#else\nreturn 7;\n#endif\n} }'
put('shared/Code.cs',source)
for name,framework in [('left','net10.0'),('right','net10.0-windows')]:
    put(name+'/'+name.title()+'.csproj',project.replace('FRAMEWORK',framework).replace('REFERENCES','<ItemGroup><ProjectReference Include="../shared/Shared.csproj" SetTargetFramework="TargetFramework='+framework+'" /></ItemGroup>'))
    put(name+'/Code.cs','public static class '+name.title()+' { public static int Read() => SharedApi.Read(); }')
put('app/App.csproj',project.replace('FRAMEWORK','net10.0-windows').replace('REFERENCES','<ItemGroup><ProjectReference Include="../left/Left.csproj"/><ProjectReference Include="../right/Right.csproj"/></ItemGroup>'))
put('app/Code.cs','return Left.Read()==7 && Right.Read()==11 ? 0 : 1;')
put('BUILD.bazel','''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_test")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
msbuild_library(name="shared_neutral",project="shared/Shared.csproj",assembly_name="SharedNeutral",srcs=["shared/Code.cs"],target_framework="net10.0",linux_worker=True)
msbuild_library(name="shared_platform",project="shared/Shared.csproj",assembly_name="SharedPlatform",srcs=["shared/Code.cs"],target_framework="net10.0-windows",linux_worker=True)
msbuild_library(name="left",project="left/Left.csproj",srcs=["left/Code.cs"],deps=[":shared_neutral"],target_framework="net10.0",linux_worker=True)
msbuild_library(name="right",project="right/Right.csproj",srcs=["right/Code.cs"],deps=[":shared_platform"],target_framework="net10.0-windows",linux_worker=True)
msbuild_test(name="app",project="app/App.csproj",srcs=["app/Code.cs"],deps=[":left",":right"],target_framework="net10.0-windows",use_apphost=False,linux_worker=True)
''')
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
run('two-configurations')
row=run('noop');assert not row['compiled'] and not row['testsExecuted'],row
put('shared/Code.cs',source.replace('return 11;','return 12;').replace('return 7;','return 8;'))
row=run('body-edit','FAIL');assert row['compiled']==['//:shared_neutral','//:shared_platform'] and row['testsExecuted']==['//:app'],row
put('shared/Code.cs',source);run('restore')

# The public contract framework must not replace the producer configuration in
# restore graph keys when two implementations of one project are paired.
put('ref/Ref.csproj',project.replace('FRAMEWORK','net10.0').replace('REFERENCES',''))
put('ref/Code.cs','public static class SharedApi { public static int Read() => throw null; }')
build=(w/'BUILD.bazel').read_text().replace('"msbuild_library","msbuild_test"','"msbuild_library","msbuild_test","msbuild_assembly"').replace('deps=[":shared_neutral"]','deps=[":paired_neutral"]').replace('deps=[":shared_platform"]','deps=[":paired_platform"]')
for name,assembly in [('neutral','SharedNeutral'),('platform','SharedPlatform')]:
    build+='\nmsbuild_library(name="contract_'+name+'",project="ref/Ref.csproj",assembly_name="'+assembly+'",srcs=["ref/Code.cs"],target_framework="net10.0",output_mode="reference",linux_worker=True)\n'
    build+='msbuild_assembly(name="paired_'+name+'",contract=":contract_'+name+'",implementation=":shared_'+name+'")\n'
put('BUILD.bazel',build)
run('paired-configurations')
put('shared/Shared.csproj',(w/'shared/Shared.csproj').read_text().replace('<TargetFrameworks>','<PackageId>SharedIdentity</PackageId><TargetFrameworks>'))
run('paired-configurations-shared-package-identity')

# One configured implementation can also arrive through both a paired compiler
# view and a direct implementation view. Their restore compatibility differs.
put('extra/Extra.csproj',project.replace('FRAMEWORK','net10.0-windows').replace('REFERENCES','<ItemGroup><ProjectReference Include="../shared/Shared.csproj" SetTargetFramework="TargetFramework=net10.0-windows" /></ItemGroup>'))
put('extra/Code.cs','public static class Extra { public static int Read() => SharedApi.Read(); }')
put('app/App.csproj',(w/'app/App.csproj').read_text().replace('</ItemGroup>','<ProjectReference Include="../extra/Extra.csproj" /></ItemGroup>'))
put('app/Code.cs','return Left.Read()==7 && Right.Read()==11 && Extra.Read()==11 ? 0 : 1;')
put('BUILD.bazel',(w/'BUILD.bazel').read_text().replace('name="paired_platform",','name="paired_platform",use_implementation_reference=True,').replace('deps=[":left",":right"]','deps=[":left",":right",":extra"]')+'\nmsbuild_library(name="extra",project="extra/Extra.csproj",srcs=["extra/Code.cs"],deps=[":shared_platform"],target_framework="net10.0-windows",linux_worker=True)\n')
run('paired-and-direct-implementation-views')
