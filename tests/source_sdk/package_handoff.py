"""Prove source -> dotnet pack -> declared package -> offline consumer handoff."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from fixture_sdk import sdk_declarations

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory', type=Path)
args = parser.parse_args()
folder = args.directory.resolve()
workspace = folder / 'src'
workspace.mkdir(parents=True)

def put(name, text):
    path = workspace / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)

put('MODULE.bazel', 'module(name="source_package_handoff")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(ROOT))+')\n'+sdk_declarations())
producer = '''<Project Sdk="Microsoft.NET.Sdk">
<PropertyGroup><TargetFramework>net10.0</TargetFramework><PackageId>Source.Package</PackageId><Version>1.0.0</Version><GeneratePackageOnBuild>true</GeneratePackageOnBuild><PackageOutputPath>bin/packages/</PackageOutputPath></PropertyGroup>

</Project>'''
put('producer/Producer.csproj', producer)
put('producer/Value.cs', 'public static class SourceValue { public static int Get() => 7; }')
put('producer/contract.json',json.dumps(dict(Version=1,Entry='Producer.csproj',SdkVersion='10.0.400',Properties={'Configuration':'Release'},SharedInputs=[],Projects={'Producer.csproj':dict(Inputs=['Producer.csproj','Value.cs'],OutputDirectories=['bin/Release/net10.0','obj/Release/net10.0','bin/packages'])})))
put('producer/BUILD.bazel', '\n'.join([
 'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph","msbuild_graph_runner","msbuild_graph_output","msbuild_generated_nuget_package")',
 'msbuild_graph_runner(name="runner")',
 'msbuild_graph(name="build",runner=":runner",contract="contract.json",source_root="producer",srcs=["Producer.csproj","Value.cs"])',
 'msbuild_graph_output(name="pack",graph=":build",path="bin/packages/Source.Package.1.0.0.nupkg")',
 'msbuild_generated_nuget_package(name="package",package_id="Source.Package",version="1.0.0",archive=":pack",visibility=["//visibility:public"])','']))
put('app/App.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><PackageReference Include="Source.Package" Version="1.0.0" /></ItemGroup></Project>')
put('app/Program.cs','System.Console.WriteLine("SOURCE_PACKAGE="+SourceValue.Get());')
put('app/contract.json',json.dumps(dict(Version=1,Entry='App.csproj',SdkVersion='10.0.400',Properties={'Configuration':'Release'},SharedInputs=[],Projects={'App.csproj':dict(Inputs=['App.csproj','Program.cs'],OutputDirectories=['bin/Release/net10.0','obj/Release/net10.0'])})))
put('app/BUILD.bazel','''load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph","msbuild_graph_runner","msbuild_graph_binary","msbuild_package_lock")
msbuild_package_lock(name="lock",packages=["//producer:package"])
msbuild_graph_runner(name="runner")
msbuild_graph(name="build",runner=":runner",contract="contract.json",source_root="app",srcs=["App.csproj","Program.cs"],package_lock=":lock",project_outputs={"App.csproj|net10.0":["bin/Release/net10.0","App.dll","Exe"]})
msbuild_graph_binary(name="app",graph=":build",project="App.csproj")
''')
base = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base='+str(folder/'base'), '--ignore_all_rc_files']
rows = []
try:
    for case, marker in [('initial', 'SOURCE_PACKAGE=7'), ('body-edit', 'SOURCE_PACKAGE=9'), ('wrong-identity', None), ('missing-output', None), ('source-archive-rejected', None)]:
        if case == 'body-edit':
            put('producer/Value.cs', 'public static class SourceValue { public static int Get() => 9; }')
        elif case == 'wrong-identity':
            put('producer/Producer.csproj', producer.replace('<PackageId>Source.Package</PackageId>', '<PackageId>Wrong.Package</PackageId>'))
        elif case == 'missing-output':
            put('producer/Producer.csproj', producer.replace('<GeneratePackageOnBuild>true</GeneratePackageOnBuild>', '<GeneratePackageOnBuild>false</GeneratePackageOnBuild>'))
        elif case == 'source-archive-rejected':
            put('producer/source.nupkg','not a generated archive')
            put('producer/BUILD.bazel',(workspace/'producer/BUILD.bazel').read_text().replace('archive=":pack"','archive="source.nupkg"'))
        command = base+['run','//app:app','--jobs=2','--lockfile_mode=off','--execution_log_json_file='+str(folder/(case+'.execution.json'))]
        result = subprocess.run(command,cwd=workspace,capture_output=True,text=True,timeout=600)
        output = result.stdout+result.stderr
        (folder/(case+'.log')).write_text(output)
        if marker:
            assert result.returncode == 0 and marker in output, output
        else:
            assert result.returncode != 0, output
            expected = {'wrong-identity':'Missing graph output','missing-output':'Missing graph output','source-archive-rejected':'must be Bazel action outputs'}[case]
            assert expected.lower() in output.lower(), output
        rows.append(dict(case=case,exitCode=result.returncode))
        print(case,result.returncode,flush=True)
finally:
    subprocess.run(base+['shutdown'],cwd=workspace,check=True)
(folder/'report.json').write_text(json.dumps(rows,indent=2)+'\n')
