"""Locked NuGet SDK resolution, worker reuse, rejection and cache recovery."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

rules = Path(__file__).resolve().parents[2]
folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True)
workspace = folder/'src'
workspace.mkdir()
sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
bazel = os.environ['RULES_MSBUILD_BAZEL']
(workspace/'MODULE.bazel').write_text(f'''module(name="sdk_packages")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(rules))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(str(sdk))},include_runtime_closure=False)
register_toolchains("//:registered")
''')
header = '''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_binary","msbuild_nuget_package","msbuild_package_lock")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
'''
for version in ['1.0.0','2.0.0']:
    archive=workspace/(version+'.nupkg')
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('Fixture.Sdk.nuspec',f'<package><metadata><id>Fixture.Sdk</id><version>{version}</version><authors>fixture</authors><description>fixture</description></metadata></package>')
        z.writestr('sdk/Sdk.props',f'<Project><PropertyGroup><AssemblyVersion>{version}</AssemblyVersion></PropertyGroup></Project>')
        z.writestr('sdk/Sdk.targets','<Project/>')
    data=archive.read_bytes()
    header+=f'msbuild_nuget_package(name="sdk_{version}",package_id="Fixture.Sdk",version="{version}",archive="{version}.nupkg",archive_sha256="{hashlib.sha256(data).hexdigest()}",content_hash="{base64.b64encode(hashlib.sha512(data).digest()).decode()}")\n'
(workspace/'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><Import Project="Sdk.props" Sdk="Fixture.Sdk"/><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup></Project>')
(workspace/'Program.cs').write_text('System.Console.WriteLine(typeof(Program).Assembly.GetName().Version);')
def configure(version, declared=None):
    (workspace/'global.json').write_text(json.dumps({'sdk':{'version':'10.0.400'},'msbuild-sdks':{'Fixture.Sdk':version}}))
    (workspace/'BUILD.bazel').write_text(header+f'msbuild_package_lock(name="lock",packages=[":sdk_{declared or version}"])\n'+ 'msbuild_binary(name="App",project="App.csproj",srcs=["Program.cs"],msbuild_imports=["global.json"],target_framework="net10.0",package_lock=":lock",linux_worker=True)\n')
startup=[bazel,'--output_base='+str(folder/'base'),'--ignore_all_rc_files']
flags=['--disk_cache='+str(folder/'cache'),'--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--remote_download_outputs=all']
reports=[]
def run(case, expected=None):
    p=subprocess.run(startup+['run','//:App','--execution_log_json_file='+str(folder/(case+'.execution.json'))]+flags,cwd=workspace,capture_output=True,text=True,timeout=240)
    (folder/(case+'.log')).write_text(p.stdout+p.stderr)
    if expected: assert p.returncode==0 and p.stdout.strip()==expected,(case,p.stdout[-1000:],p.stderr[-4000:])
    else: assert p.returncode!=0 and "Fixture.Sdk" in p.stderr and 'could not be found' in p.stderr,p.stderr[-4000:]
    reports.append({'case':case,'exitCode':p.returncode,'output':p.stdout.strip()})
    print(case,p.returncode,flush=True)
try:
    configure('1.0.0');run('initial','1.0.0.0')
    configure('2.0.0');run('new-version-same-worker','2.0.0.0')
    configure('1.0.0','2.0.0');run('undeclared-version')
    configure('2.0.0');run('recovered-version','2.0.0.0')
    subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
    relocated=folder/'relocated';shutil.copytree(workspace,relocated,ignore=shutil.ignore_patterns('bazel-*'))
    shutil.rmtree(workspace);shutil.rmtree(folder/'base');workspace=relocated
    startup=[bazel,'--output_base='+str(folder/'fresh-base'),'--output_user_root='+str(folder/'fresh-user'),'--ignore_all_rc_files']
    run('relocated-cache','2.0.0.0')
    text=(folder/'relocated-cache.execution.json').read_text();decoder=json.JSONDecoder();actions=[]
    while text.strip():
        action,end=decoder.raw_decode(text.lstrip());text=text.lstrip()[end:]
        if action.get('mnemonic')=='MSBuildAssembly':actions.append(action)
    assert len(actions)==1 and actions[0].get('cacheHit'),actions
finally:
    subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
(folder/'report.json').write_text(json.dumps(reports,indent=2)+'\n')
