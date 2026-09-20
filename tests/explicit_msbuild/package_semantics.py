"""Central version and private compile-flow controls using a real local package."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

folder=Path(sys.argv[1]).resolve();workspace=folder/'src';sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);bazel=os.environ['RULES_MSBUILD_BAZEL']
pack=folder/'hidden-package';pack.mkdir(exist_ok=True)
(pack/'Hidden.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><PackageId>Hidden</PackageId><Version>1.0.0</Version></PropertyGroup></Project>')
(pack/'Hidden.cs').write_text('public static class HiddenType { public static int Get() => 7; }')
p=subprocess.run([str(sdk/'dotnet'),'pack',str(pack/'Hidden.csproj'),'-c','Release','-o',str(pack/'nupkg'),'-p:NuGetAudit=false'],capture_output=True,text=True)
assert p.returncode==0,p.stdout+p.stderr
packages=workspace/'private-packages';packages.mkdir(exist_ok=True);archive=packages/'Hidden.1.0.0.nupkg';shutil.copyfile(pack/'nupkg/Hidden.1.0.0.nupkg',archive)
import base64
(packages/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package")\nmsbuild_nuget_package(name="hidden",package_id="Hidden",version="1.0.0",archive="Hidden.1.0.0.nupkg",archive_sha256='+json.dumps(hashlib.sha256(archive.read_bytes()).hexdigest())+',content_hash='+json.dumps(base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode())+',visibility=["//visibility:public"])\n')
lib=workspace/'PrivateLibrary';lib.mkdir(exist_ok=True)
project='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="Hidden" PrivateAssets="all" /></ItemGroup></Project>'
(lib/'PrivateLibrary.csproj').write_text(project)
(lib/'Value.cs').write_text('public static class PrivateValue { public static int Get() => 7; public static int UsePrivate() => HiddenType.Get(); }')
props='<Project><PropertyGroup><ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally><CentralPackageTransitivePinningEnabled>true</CentralPackageTransitivePinningEnabled></PropertyGroup><ItemGroup><PackageVersion Include="Hidden" Version="1.0.0" /></ItemGroup></Project>'
(lib/'Directory.Packages.props').write_text(props)
build='load("@rules_msbuild//msbuild:defs.bzl","msbuild_library")\nmsbuild_library(name="PrivateLibrary",project="PrivateLibrary.csproj",target_framework="net10.0",srcs=["Value.cs"],deps=["//private-packages:hidden"],msbuild_imports=["Directory.Packages.props"],package_private_assets={"Hidden":"all"},linux_worker=True,visibility=["//visibility:public"])\n'
(lib/'BUILD.bazel').write_text(build)
app=workspace/'PrivateConsumer';app.mkdir(exist_ok=True)
(app/'PrivateConsumer.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../PrivateLibrary/PrivateLibrary.csproj" /></ItemGroup></Project>')
(app/'Program.cs').write_text('System.Console.WriteLine(PrivateValue.Get());')
(app/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_binary")\nmsbuild_binary(name="PrivateConsumer",project="PrivateConsumer.csproj",target_framework="net10.0",srcs=["Program.cs"],deps=["//PrivateLibrary"],linux_worker=True)\n')
cmd=[bazel,'--output_base='+str(folder/'private-base'),'--ignore_all_rc_files'];rows=[]
def run(case,error=None):
 p=subprocess.run(cmd+['run','//PrivateConsumer','--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE'],'--disk_cache=','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1'],cwd=workspace,capture_output=True,text=True,timeout=240)
 output=p.stdout+p.stderr;(folder/(case+'.log')).write_text(output)
 assert (p.returncode==0 and p.stdout.strip()=='7') if error is None else (p.returncode!=0 and error in output),(case,output[-5000:])
 rows.append(dict(case=case,exit=p.returncode));print(case,p.returncode,flush=True)
run('private-library-consumer')
(app/'Program.cs').write_text('System.Console.WriteLine(HiddenType.Get());')
run('private-compile-rejected','CS0103')
(lib/'PrivateLibrary.csproj').write_text(project.replace('PrivateAssets="all"','PrivateAssets="none"'))
run('private-metadata-mismatch','PrivateAssets disagrees')
(lib/'BUILD.bazel').write_text(build.replace('"Hidden":"all"','"Hidden":"none"'))
run('public-compile')
(lib/'Directory.Packages.props').write_text(props.replace('Version="1.0.0"','Version="2.0.0"'))
run('central-version-mismatch','version disagrees with lock')
(lib/'Directory.Packages.props').write_text(props.replace('Version="1.0.0"','Version="[1.0.0,2.0.0)"'))
run('central-version-range')
(lib/'Directory.Packages.props').write_text(props)
run('package-recovered')
(folder/'package-report.json').write_text(json.dumps(rows,indent=2))
subprocess.run(cmd+['shutdown'],cwd=workspace,check=True)
