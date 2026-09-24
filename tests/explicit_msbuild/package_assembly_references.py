"""Exact package DLL references retain metadata and reject undeclared inputs."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

rules = Path(__file__).resolve().parents[2]
folder = Path(sys.argv[1]).resolve(); folder.mkdir(parents=True)
workspace = folder/'src'; workspace.mkdir()
sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
bazel = os.environ['RULES_MSBUILD_BAZEL']
producer = folder/'producer'; producer.mkdir()
(producer/'Fixture.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
(producer/'Api.cs').write_text('public static class Api { public const int Value = 7; }')
subprocess.run([sdk/'dotnet', 'build', producer/'Fixture.csproj', '-c', 'Release'], check=True)
archive = workspace/'fixture.nupkg'
with zipfile.ZipFile(archive, 'w') as package:
    package.writestr('Fixture.Library.nuspec', '<package><metadata><id>Fixture.Library</id><version>1.0.0</version><authors>fixture</authors><description>fixture</description></metadata></package>')
    package.write(producer/'bin/Release/net10.0/Fixture.dll', 'ref/net10.0/Fixture.dll')
data = archive.read_bytes()
(workspace/'MODULE.bazel').write_text(f'''module(name="package_assemblies")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(rules))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(str(sdk))},include_runtime_closure=False)
register_toolchains("//:registered")
''')
header = f'''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_binary","msbuild_nuget_package","msbuild_package_lock")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
msbuild_nuget_package(name="archive",package_id="Fixture.Library",version="1.0.0",archive="fixture.nupkg",archive_sha256="{hashlib.sha256(data).hexdigest()}",content_hash="{base64.b64encode(hashlib.sha512(data).digest()).decode()}")
msbuild_package_lock(name="lock",packages=[":archive"])
'''
project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><Reference Include="$(RestorePackagesPath)/fixture.library/1.0.0/ref/net10.0/Fixture.dll" Private="false" /></ItemGroup></Project>'
(workspace/'App.csproj').write_text(project)
(workspace/'Program.cs').write_text('System.Console.WriteLine(Api.Value);')
startup = [bazel, '--output_base='+str(folder/'base'), '--ignore_all_rc_files']
reports=[]
def run(case, paths, error=None):
    (workspace/'BUILD.bazel').write_text(header+'msbuild_binary(name="App",project="App.csproj",target_framework="net10.0",srcs=["Program.cs"],package_lock=":lock",package_reference_paths='+json.dumps(paths)+',linux_worker=True)\n')
    result = subprocess.run(startup+['run','//:App','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1'],cwd=workspace,capture_output=True,text=True,timeout=240)
    output=result.stdout+result.stderr; (folder/(case+'.log')).write_text(output)
    assert (result.returncode != 0 and error in output) if error else (result.returncode == 0 and result.stdout.strip() == '7'),output[-4000:]
    reports.append({'case':case,'exitCode':result.returncode}); print(case,result.returncode,flush=True)
paths={'Fixture.Library':['ref/net10.0/Fixture.dll']}
try:
    run('declared-package-dll',paths)
    assert not (workspace/'bazel-bin/App.runtime/Fixture.dll').exists(), 'Private=false must remain effective'
    run('undeclared-package-dll',{},'Undeclared assembly/analyzer dependency')
    run('missing-package',{'Other':['ref/net10.0/Fixture.dll']},'requires a locked package')
    run('missing-file',{'Fixture.Library':['ref/net10.0/Missing.dll']},'Missing declared package assembly')
    run('unsafe-path',{'Fixture.Library':['../Fixture.dll']},'Unsafe')
    run('duplicate-declaration',{'Fixture.Library':['ref/net10.0/Fixture.dll']*2},'exactly one matching Reference')
    (workspace/'App.csproj').write_text(project.replace('Private="false"','Private="false" Aliases="other"'))
    run('alias-rejected',paths,'Unsupported package assembly Reference metadata')
    (workspace/'App.csproj').write_text(project)
    run('recovered',paths)
finally:
    subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
(folder/'report.json').write_text(json.dumps(reports,indent=2)+'\n')
