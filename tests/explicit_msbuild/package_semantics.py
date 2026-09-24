"""Central version and private compile-flow controls using a real local package."""
import hashlib
import zipfile
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
# Add a real NuGet compile content file, as source-only packages do.
with zipfile.ZipFile(archive) as original:
 payload={name:original.read(name) for name in original.namelist()}
nuspec=next(name for name in payload if name.endswith('.nuspec'))
payload[nuspec]=payload[nuspec].decode('utf-8-sig').replace('</metadata>', '<contentFiles><files include="cs/any/PackageContent.cs" buildAction="Compile" /></contentFiles></metadata>').encode()
payload['contentFiles/cs/any/PackageContent.cs']=b'internal static class PackageContent { public static int Get() => 7; }'
with zipfile.ZipFile(archive,'w') as modified:
 for name,data in payload.items():modified.writestr(name,data)
import base64
(packages/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package")\nmsbuild_nuget_package(name="hidden",package_id="Hidden",version="1.0.0",archive="Hidden.1.0.0.nupkg",archive_sha256='+json.dumps(hashlib.sha256(archive.read_bytes()).hexdigest())+',content_hash='+json.dumps(base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode())+',visibility=["//visibility:public"])\n')
lib=workspace/'PrivateLibrary';lib.mkdir(exist_ok=True)
project='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="Hidden" PrivateAssets="all" /></ItemGroup></Project>'
(lib/'PrivateLibrary.csproj').write_text(project)
(lib/'Value.cs').write_text('public static class PrivateValue { public static int Get() => PackageContent.Get(); public static int UsePrivate() => HiddenType.Get(); }')
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
# Metadata-preserving restore must emit NuGet's path property for a declared package.
(app/'Program.cs').write_text('System.Console.WriteLine(PrivateValue.Get());')
(lib/'BUILD.bazel').write_text(build)
path_project=project.replace('PrivateAssets="all"', 'PrivateAssets="all" GeneratePathProperty="true"').replace('</Project>', '''<Target Name="VerifyPackagePath" BeforeTargets="CoreCompile"><Error Condition="!Exists('$(PkgHidden)/lib/net10.0/Hidden.dll')" Text="Missing generated package path" /></Target></Project>''')
(lib/'PrivateLibrary.csproj').write_text(path_project)
run('generated-package-path')
(lib/'PrivateLibrary.csproj').write_text(path_project.replace('GeneratePathProperty="true"','GeneratePathProperty="invalid"'))
run('invalid-generated-package-path','Invalid PackageReference GeneratePathProperty')
# A locked build package can be introduced implicitly by an SDK restore target.
# It must not acquire an unrelated central PackageVersion before that target runs.
(lib/'Directory.Packages.props').write_text('<Project><PropertyGroup><ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally></PropertyGroup></Project>')
(lib/'PrivateLibrary.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><Target Name="AddImplicitPackage" BeforeTargets="_GenerateRestoreGraphProjectEntry"><ItemGroup><PackageReference Include="Hidden" Version="[1.0.0]" IsImplicitlyDefined="true" /></ItemGroup></Target></Project>')
(lib/'Value.cs').write_text('public static class PrivateValue { public static int Get() => 7; }')
(lib/'BUILD.bazel').write_text(build.replace('deps=["//private-packages:hidden"]','build_deps=["//private-packages:hidden"]'))
run('late-implicit-package-central-management')
# A restore-only baseline download is independent of an unused central version.
(lib/'Directory.Packages.props').write_text(props.replace('Version="1.0.0"','Version="2.0.0"'))
(lib/'PrivateLibrary.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageDownload Include="Hidden" Version="[1.0.0]" /></ItemGroup></Project>')
lock_build=build.replace('"msbuild_library"','"msbuild_library","msbuild_package_lock"').replace('deps=["//private-packages:hidden"]','package_lock=":baseline"').replace('package_private_assets={"Hidden":"all"},','')
(lib/'BUILD.bazel').write_text(lock_build+'msbuild_package_lock(name="baseline",packages=["//private-packages:hidden"])\n')
run('download-independent-of-unused-central-version')
# NuGet dependency asset filters must survive a declared package closure. Merely
# making an archive available must not promote it to a direct PackageReference.
root_archive = packages/'Filtered.1.0.0.nupkg'
with zipfile.ZipFile(root_archive, 'w') as package:
 package.writestr('Filtered.nuspec', '<package><metadata><id>Filtered</id><version>1.0.0</version><authors>fixture</authors><description>fixture</description><dependencies><group targetFramework="net10.0"><dependency id="Hidden" version="[1.0.0]" exclude="Compile" /></group></dependencies></metadata></package>')
with (packages/'BUILD.bazel').open('a') as file:
 file.write('msbuild_nuget_package(name="filtered",package_id="Filtered",version="1.0.0",archive="Filtered.1.0.0.nupkg",archive_sha256='+json.dumps(hashlib.sha256(root_archive.read_bytes()).hexdigest())+',content_hash='+json.dumps(base64.b64encode(hashlib.sha512(root_archive.read_bytes()).digest()).decode())+',deps=[":hidden"],visibility=["//visibility:public"])\n')
(lib/'Directory.Packages.props').write_text('<Project/>')
(lib/'PrivateLibrary.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="Filtered" Version="1.0.0" /></ItemGroup></Project>')
(lib/'BUILD.bazel').write_text(build.replace('//private-packages:hidden','//private-packages:filtered').replace('package_private_assets={"Hidden":"all"},',''))
(lib/'Value.cs').write_text('public static class PrivateValue { public static int Get() => 7; }')
run('filtered-transitive-package')
(lib/'Value.cs').write_text('public static class PrivateValue { public static int Get() => HiddenType.Get(); }')
run('filtered-transitive-compile-rejected', 'CS0103')
(lib/'Value.cs').write_text('public static class PrivateValue { public static int Get() => 7; }')
run('filtered-transitive-recovery')
# An unused central entry must not constrain a transitive build dependency unless
# the project explicitly enables NuGet central transitive pinning.
central='<Project><PropertyGroup><ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally></PropertyGroup><ItemGroup><PackageVersion Include="Filtered" Version="1.0.0"/><PackageVersion Include="Hidden" Version="2.0.0"/></ItemGroup></Project>'
(lib/'Directory.Packages.props').write_text(central)
(lib/'PrivateLibrary.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="Filtered"/></ItemGroup></Project>')
(lib/'BUILD.bazel').write_text(build.replace('//private-packages:hidden','//private-packages:filtered').replace('package_private_assets={"Hidden":"all"},','build_deps=["//private-packages:filtered"],'))
run('unused-central-transitive-build-version')
(lib/'Directory.Packages.props').write_text(central.replace('</PropertyGroup>','<CentralPackageTransitivePinningEnabled>true</CentralPackageTransitivePinningEnabled></PropertyGroup>'))
run('active-central-transitive-build-version', 'version disagrees with lock')
(lib/'Directory.Packages.props').write_text(central)
run('central-transitive-build-recovered')
(folder/'package-report.json').write_text(json.dumps(rows,indent=2))
subprocess.run(cmd+['shutdown'],cwd=workspace,check=True)
