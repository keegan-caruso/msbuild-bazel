"""Private project compiler visibility preserves raw MSBuild runtime behavior."""
import json
import os
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[2];out=Path(sys.argv[1]).resolve();w=out/'source';w.mkdir(parents=True)
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);bazel=os.environ['RULES_MSBUILD_BAZEL']
def put(name,text):
 p=w/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
for name,refs,code in [
 ('Hidden','','public class Hidden { public static int Value => 42; }'),
 ('Middle','<ProjectReference Include="../Hidden/Hidden.csproj" PrivateAssets="all" />','public class Middle { public static int Value => Hidden.Value; }'),
 ('App','<ProjectReference Include="../Middle/Middle.csproj" />','System.Console.WriteLine(Middle.Value); return Middle.Value == 42 ? 0 : 1;')]:
 put(name+'/'+name+'.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>'+('<OutputType>Exe</OutputType>' if name=='App' else '')+'</PropertyGroup><ItemGroup>'+refs+'</ItemGroup></Project>')
 put(name+'/Code.cs',code)
original=(w/'App/Code.cs').read_text()
def raw(name,negative=False):
 result=subprocess.run([sdk/'dotnet','build',w/'App/App.csproj','-c','Release'],text=True,capture_output=True)
 (out/(name+'.log')).write_text(result.stdout+result.stderr)
 assert (result.returncode != 0)==negative,result.stdout+result.stderr
 if negative:assert 'CS0103' in result.stdout
raw('raw')
assert subprocess.check_output([sdk/'dotnet',w/'App/bin/Release/net10.0/App.dll'],text=True).strip()=='42'
put('App/Code.cs',original.replace('Middle.Value','Hidden.Value'));raw('raw-hidden-reference',True);put('App/Code.cs',original)
put('MODULE.bazel',f'''module(name="implementation_deps")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(root))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(str(sdk))},include_runtime_closure=False)
register_toolchains("//:registered")
''')
put('BUILD.bazel','''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_test")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
msbuild_library(name="Hidden",project="Hidden/Hidden.csproj",srcs=["Hidden/Code.cs"],target_framework="net10.0",linux_worker=True)
msbuild_library(name="Middle",project="Middle/Middle.csproj",srcs=["Middle/Code.cs"],implementation_deps=[":Hidden"],target_framework="net10.0",linux_worker=True)
msbuild_test(name="App",project="App/App.csproj",srcs=["App/Code.cs"],deps=[":Middle"],target_framework="net10.0",use_apphost=False,linux_worker=True)
''')
base=out/'base';records=[]
def run(name,error=None):
 result=subprocess.run([bazel,'--output_base='+str(base),'--ignore_all_rc_files','test','//:App','--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--disk_cache=','--test_output=errors'],cwd=w,text=True,capture_output=True,timeout=240)
 text=result.stdout+result.stderr;(out/(name+'.log')).write_text(text)
 assert (result.returncode!=0)==bool(error),(name,text[-3000:])
 if error:assert error in text,(name,text[-3000:])
 records.append(dict(case=name,exitCode=result.returncode));(out/'report.json').write_text(json.dumps(records,indent=2)+'\n');print(records[-1],flush=True)
try:
 run('private-runtime')
 request=json.loads((w/'bazel-bin/App.request.json').read_text())
 assert not any(p.endswith('/Hidden.dll') for p in request['references'])
 assert any(p.endswith('/Hidden.dll') for p in request['runtimeReferences'])
 put('App/Code.cs',original.replace('Middle.Value','Hidden.Value'))
 run('private-compiler-rejected','failed')
 assert 'CS0103' in (w/'bazel-bin/App.diagnostics/build.log').read_text()
 put('App/Code.cs',original)
 run('restored')
 build=(w/'BUILD.bazel').read_text();put('BUILD.bazel',build.replace('implementation_deps=[":Hidden"]','deps=[":Hidden"]'))
 run('visibility-mismatch','PrivateAssets disagrees')
finally:
 put('App/Code.cs',original)
 subprocess.run([bazel,'--output_base='+str(base),'shutdown'],cwd=w,check=True)
