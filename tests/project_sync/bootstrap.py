"""Bazel-produced evaluation inputs and a closed NuGet SDK in a fresh workspace."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

rules=Path(__file__).resolve().parents[2]
folder=Path(sys.argv[1]).resolve();folder.mkdir(parents=True,exist_ok=False)
workspace=folder/'src';workspace.mkdir()
bazel=os.environ.get('RULES_MSBUILD_BAZEL',str(rules/'scripts/bazel-launcher.sh'))
cmd=[bazel,'--output_base='+str(folder/'base'),'--ignore_all_rc_files']
rows=[]
def put(path,text):
 p=workspace/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
def run(name,args,expected=None,error=None):
 p=subprocess.run(cmd+args,cwd=workspace,text=True,capture_output=True)
 output=p.stdout+p.stderr;(folder/(name+'.log')).write_text(output)
 assert (p.returncode==0) if error is None else (p.returncode!=0 and error in output),(name,output[-6000:])
 if expected is not None:assert p.stdout.strip().splitlines()[-1]==expected,(name,p.stdout[-1000:])
 rows.append(dict(case=name,exit=p.returncode));print(name,p.returncode,flush=True)
put('MODULE.bazel','module(name="sync_bootstrap")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(rules))+')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",global_json="//:global.json")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
global_json=json.loads((rules/'global.json').read_text());global_json['msbuild-sdks']={'Example.Build.Sdk':'1.0.0'}
put('global.json',json.dumps(global_json))
shutil.copyfile(rules/'.bazelversion',workspace/'.bazelversion')
with zipfile.ZipFile(workspace/'sdk.nupkg','w') as z:
 z.writestr('Example.Build.Sdk.nuspec','<package><metadata><id>Example.Build.Sdk</id><version>1.0.0</version><authors>fixture</authors><description>fixture</description></metadata></package>')
 z.writestr('Sdk/Sdk.props','<Project><PropertyGroup><DefineConstants>$(DefineConstants);SDK_OK</DefineConstants></PropertyGroup></Project>')
 z.writestr('Sdk/Sdk.targets','<Project/>')
data=(workspace/'sdk.nupkg').read_bytes()
put('seed.props','<Project><PropertyGroup><TargetFramework>net10.0</TargetFramework><DefineConstants>BOOTSTRAP</DefineConstants></PropertyGroup></Project>')
put('resource.seed','bootstrap resource')
put('Generate/Generate.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><Target Name="Generate"><Copy SourceFiles="../seed.props" DestinationFiles="$(GeneratedProps)"/><Copy SourceFiles="../resource.seed" DestinationFiles="$(GeneratedResource)"/></Target></Project>')
put('value.seed','public static class Generated { public static int Value => 7; }')
put('App/App.csproj','<Project Sdk="Microsoft.NET.Sdk"><Import Project="../artifacts/generated.props"/><Import Project="Sdk.props" Sdk="Example.Build.Sdk"/><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><Compile Include="../artifacts/Generated.cs"/><EmbeddedResource Include="../artifacts/message.txt" LogicalName="message"/></ItemGroup></Project>')
put('App/Program.cs','#if BOOTSTRAP && SDK_OK\nusing var stream = System.Reflection.Assembly.GetExecutingAssembly().GetManifestResourceStream("message");\nif (stream is null) throw new System.Exception("Missing generated resource");\nSystem.Console.WriteLine(Generated.Value);\n#else\n#error Missing declared bootstrap/SDK\n#endif\n')
authored='''load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package","msbuild_package_lock","msbuild_generate")
exports_files(["global.json"])
msbuild_generate(name="bootstrap",project="Generate/Generate.csproj",target_framework="net10.0",msbuild_imports=["seed.props","resource.seed"],targets=["Generate"],outputs=["generated.props","message.txt"],output_properties={"GeneratedProps":"generated.props","GeneratedResource":"message.txt"})
filegroup(name="props",srcs=[":bootstrap"],output_group="generated.props")
filegroup(name="resource",srcs=[":bootstrap"],output_group="message.txt")
genrule(name="code",srcs=["value.seed"],outs=["bootstrap.cs"],cmd="cp $(location value.seed) $@")
msbuild_nuget_package(name="sdk",package_id="Example.Build.Sdk",version="1.0.0",archive="sdk.nupkg",archive_sha256="%s",content_hash="%s")
msbuild_package_lock(name="lock",packages=[":sdk"])
msbuild_sync(name="sync",projects=["App/App.csproj"],inputs={":props":"artifacts/generated.props",":code":"artifacts/Generated.cs",":resource":"artifacts/message.txt"},package_lock=":lock")
'''%(hashlib.sha256(data).hexdigest(),base64.b64encode(hashlib.sha512(data).digest()).decode())
put('BUILD.bazel',authored)
try:
 run('bootstrap',['run','//:sync'])
 generated=(workspace/'projects.generated.bzl').read_text()
 assert 'source_paths' in generated and 'import_paths' in generated and 'package_lock' in generated
 assert 'msbuild-sync-' not in generated and str(folder) not in generated
 assert not (workspace/'artifacts').exists()
 put('BUILD.bazel','load(":projects.generated.bzl","app_projects")\n'+authored+'app_projects()\n')
 run('run',['run','//:App_App','--jobs=2'],expected='7')
 put('value.seed','public static class Generated { public static int Value => 9; }')
 run('producer-edit',['run','//:App_App','--jobs=2'],expected='9')
 run('check',['run','//:sync','--','--check'])
 global_json['msbuild-sdks']['Example.Build.Sdk']='9.9.9';put('global.json',json.dumps(global_json))
 run('missing-sdk',['run','//:sync'],error='Example.Build.Sdk')
 assert (workspace/'projects.generated.bzl').read_text()==generated
finally:
 subprocess.run(cmd+['shutdown'],cwd=workspace,check=True)
 (folder/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
