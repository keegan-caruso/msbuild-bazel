"""Small build controls for repository configuration, explicit items and package privacy.

Run with a new disposable directory. Uses bazel run //:sync and a locally packed
NuGet dependency; does not qualify either upstream repository.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT/'.tools/dotnet'))
BAZEL = os.environ.get('RULES_MSBUILD_BAZEL', str(ROOT/'scripts/bazel-launcher.sh'))
folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=False)
workspace = folder/'src'
workspace.mkdir()
rows = []

def put(path, text):
    dest = workspace/path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text)


def command(name, args, expected=None, error=None, cwd=workspace):
    result = subprocess.run([str(a) for a in args], cwd=cwd, text=True, capture_output=True)
    output = result.stdout+result.stderr
    (folder/(name+'.log')).write_text(output)
    assert (result.returncode == 0) if error is None else (result.returncode != 0 and error in output), (name, output[-7000:])
    if expected is not None:
        assert result.stdout.strip().splitlines()[-1] == expected, (name, result.stdout[-1500:])
    rows.append(dict(case=name, exit=result.returncode))
    print(name, result.returncode, flush=True)
    return result

pack = folder/'pack'
pack.mkdir()
(pack/'Hidden.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><Version>1.0.0</Version></PropertyGroup></Project>')
(pack/'Hidden.cs').write_text('public static class HiddenType { public static int Value => 7; }')
command('pack', [SDK/'dotnet','pack',pack/'Hidden.csproj','-c','Release','-o',pack/'packages','-p:NuGetAudit=false'], cwd=pack)
put('packages/BUILD.bazel', '')
archive = workspace/'packages/Hidden.1.0.0.nupkg'
shutil.copyfile(pack/'packages/Hidden.1.0.0.nupkg', archive)
put('packages/BUILD.bazel', 'load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package")\nmsbuild_nuget_package(name="hidden",package_id="Hidden",version="1.0.0",archive="Hidden.1.0.0.nupkg",archive_sha256='+json.dumps(hashlib.sha256(archive.read_bytes()).hexdigest())+',content_hash='+json.dumps(base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode())+',visibility=["//visibility:public"])\n')
put('MODULE.bazel', 'module(name="sync_compatibility")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(ROOT))+')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",global_json="//:global.json")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
shutil.copyfile(ROOT/'global.json', workspace/'global.json')
shutil.copyfile(ROOT/'.bazelversion', workspace/'.bazelversion')
put('Directory.Build.props','<Project><PropertyGroup><TargetFramework>net10.0</TargetFramework><TreatWarningsAsErrors>true</TreatWarningsAsErrors></PropertyGroup></Project>')
put('Directory.Packages.props','<Project><PropertyGroup><ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally></PropertyGroup><ItemGroup><PackageVersion Include="Hidden" Version="1.0.0"/></ItemGroup></Project>')
project = '''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework/><TargetFrameworks>net9.0;net10.0</TargetFrameworks></PropertyGroup><ItemGroup><PackageReference Include="Hidden" PrivateAssets="all"/><Compile Include="../Shared/Value.cs" Link="Shared/Value.cs"/><EmbeddedResource Include="message.txt" LogicalName="Probe.Message"/><AdditionalFiles Include="options.txt"/><None Update="options.txt" CopyToOutputDirectory="PreserveNewest"/></ItemGroup><ItemGroup Condition="'$(Flavor)' != 'extra'"><Compile Remove="Extra.cs"/></ItemGroup></Project>'''
put('Library/Library.csproj', project)
put('Shared/Value.cs','public static class Value { public static int Number => 7; internal static int PrivateUse => HiddenType.Value; public static string Message { get { using var reader = new System.IO.StreamReader(typeof(Value).Assembly.GetManifestResourceStream("Probe.Message")); return reader.ReadToEnd(); } } }')
put('Library/Extra.cs','public static class Extra { public static string Text => "extra"; }')
put('Library/message.txt','hello')
put('Library/options.txt','options')
put('App/App.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Library/Library.csproj"/></ItemGroup></Project>')
program = 'System.Console.WriteLine($"{Value.Number}:{Value.Message}:{Extra.Text}");'
put('App/Program.cs', program)
mapping = dict(projects={'Library/Library.csproj':dict(targetFrameworks=['net10.0'],properties={'Flavor':'extra'})},packages={'Hidden/1.0.0':dict(label='//packages:hidden',roles=['deps'])})
put('sync.json', json.dumps(mapping))
authored = 'load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\nexports_files(["global.json"])\nmsbuild_sync(name="sync",projects=["App/App.csproj"],mappings="sync.json")\n'
put('BUILD.bazel', authored)
cmd = [BAZEL,'--output_base='+str(folder/'base'),'--ignore_all_rc_files']
try:
    command('sync', cmd+['run','//:sync'])
    put('BUILD.bazel','load(":projects.generated.bzl","app_projects")\n'+authored+'app_projects()\n')
    command('build-run', cmd+['run','//:App_App','--jobs=2'], expected='7:hello:extra')
    assert 'CS2002' not in (folder/'build-run.log').read_text()
    assert (workspace/'bazel-bin/Library_Library_net10_0.runtime/options.txt').read_text() == 'options'
    command('check', cmd+['run','//:sync','--','--check'])
    put('Library/message.txt','changed')
    command('resource-edit', cmd+['run','//:App_App','--jobs=2'], expected='7:changed:extra')
    put('App/Program.cs','System.Console.WriteLine(HiddenType.Value);')
    command('private-consumer-rejected', cmd+['build','//:App_App','--jobs=2'], error='CS0103')
    put('Library/Library.csproj', project.replace('PrivateAssets="all"','PrivateAssets="none"'))
    command('privacy-drift', cmd+['run','//:sync','--','--check'], error='stale')
    command('resync', cmd+['run','//:sync'])
    command('public-consumer', cmd+['run','//:App_App','--jobs=2'], expected='7')
finally:
    subprocess.run(cmd+['shutdown'],cwd=workspace,check=True)
    (folder/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
