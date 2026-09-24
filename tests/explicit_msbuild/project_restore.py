"""Project-over-package identity without evaluating dependency SDK projects.

Run after acceptance.py (or project_outputs.py), which supplies the toolchain.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

folder = Path(sys.argv[1]).resolve()
workspace = folder/'src'
root = workspace/'restore-identity'
root.mkdir(exist_ok=True)
(root/'Library').mkdir(exist_ok=True)
(root/'App').mkdir(exist_ok=True)
package_source = folder/'outer-package-source'
package_source.mkdir(exist_ok=True)
(package_source/'Outer.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
(package_source/'Marker.cs').write_text('public static class OuterMarker { public static int Zero => 0; }')
subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'),'build',str(package_source/'Outer.csproj'),'-c','Release','-p:NuGetAudit=false'],check=True,stdout=subprocess.DEVNULL)
archive = root/'Outer.1.0.0.nupkg'
with zipfile.ZipFile(archive, 'w') as package:
    package.write(package_source/'bin/Release/net10.0/Outer.dll', 'lib/net10.0/Outer.dll')
    package.writestr('Outer.nuspec', '<package><metadata><id>Outer</id><version>1.0.0</version><authors>fixture</authors><description>fixture</description><dependencies><group targetFramework="net10.0"><dependency id="Dependency.Identity" version="[1.0.0,)" /></group></dependencies></metadata></package>')
def library(version, value):
    (root/'Library/Unrelated.csproj').write_text(f'<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><PackageId>Dependency.Identity</PackageId><PackageVersion>{version}</PackageVersion></PropertyGroup></Project>')
    (root/'Library/Value.cs').write_text(f'public static class LibraryValue {{ public static int Get() => {value}; }}')
(root/'App/App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Library/Unrelated.csproj"/><PackageReference Include="Outer" Version="1.0.0" /></ItemGroup></Project>')
(root/'App/Program.cs').write_text('System.Console.WriteLine(LibraryValue.Get() + OuterMarker.Zero);')
(root/'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl", "msbuild_library", "msbuild_binary", "msbuild_nuget_package")
msbuild_library(name="library",project="Library/Unrelated.csproj",assembly_name="Different.Assembly",srcs=["Library/Value.cs"],target_framework="net10.0",linux_worker=True)
msbuild_binary(name="app",project="App/App.csproj",srcs=["App/Program.cs"],target_framework="net10.0",deps=[":library",":outer"],linux_worker=True)
'''+f'msbuild_nuget_package(name="outer",package_id="Outer",version="1.0.0",archive="Outer.1.0.0.nupkg",archive_sha256="{hashlib.sha256(archive.read_bytes()).hexdigest()}",content_hash="{base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()}")\n')
startup = [os.environ['RULES_MSBUILD_BAZEL'], '--host_jvm_args=-Xmx1024m', '--output_base='+str(folder/'identity-base'), '--ignore_all_rc_files']
rows = []
def run(case, value, version):
    result = subprocess.run(startup+['run','//restore-identity:app','--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--disk_cache='],cwd=workspace,capture_output=True,text=True,timeout=240)
    (folder/(case+'.log')).write_text(result.stdout+result.stderr)
    assert result.returncode == 0 and result.stdout.strip() == str(value), (case, result.stdout[-1000:], result.stderr[-5000:])
    output = workspace/'bazel-bin/restore-identity'
    identity = json.loads((output/'library.restore-project.json').read_text())
    assert identity['name'] == 'Dependency.Identity' and identity['version'] == version, identity
    deps = json.loads((output/'app.runtime/App.deps.json').read_text())
    assert deps['libraries']['Dependency.Identity/'+version]['type'] == 'project', deps['libraries']
    assert deps['libraries']['Outer/1.0.0']['type'] == 'package', deps['libraries']
    rows.append(dict(case=case,output=value,version=version))
    print(case, 'passed', flush=True)
try:
    library('2.0.0',7);run('project-replaces-missing-package',7,'2.0.0')
    library('3.0.0',7);run('project-package-version-change',7,'3.0.0')
    library('3.0.0',8);run('project-body-change',8,'3.0.0')
finally:
    subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
(folder/'project-restore-report.json').write_text(json.dumps(rows,indent=2)+'\n')
