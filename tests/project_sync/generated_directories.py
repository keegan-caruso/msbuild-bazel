"""Source-relative generated directories remain writable without writable inputs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(sys.argv[1]).resolve(); root.mkdir(parents=True, exist_ok=False)
w = root / 'workspace'; w.mkdir()
rules = Path(__file__).resolve().parents[2]
def put(name, text):
    path = w / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
project = '''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><EmbeddedResource Include="z.txt" LogicalName="Z"/><EmbeddedResource Include="a.txt" LogicalName="A"/></ItemGroup><Target Name="WriteGenerated" AfterTargets="Build"><MakeDir Directories="Generated/nested"/><WriteLinesToFile File="Generated/nested/value.txt" Lines="$(GeneratedValue)" Overwrite="true"/></Target></Project>'''
put('App/App.csproj', project)
put('App/z.txt', 'Z'); put('App/a.txt', 'A')
put('App/é中😀.cs', 'internal class UnicodeSource {}')
put('App/Program.cs', 'if (string.Join(",", typeof(Program).Assembly.GetManifestResourceNames()) != "Z,A") throw new System.Exception("Resource order changed"); System.Console.WriteLine(System.IO.File.ReadAllText(System.IO.Path.Combine(System.AppContext.BaseDirectory,"data/nested/value.txt")).Trim());')
put('MODULE.bazel', 'module(name="sync_generated_directories")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path=' + json.dumps(str(rules)) + ')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",version="10.0.400")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
shutil.copyfile(rules / '.bazelversion', w / '.bazelversion')
authored = 'load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\nmsbuild_sync(name="sync",projects=["App/App.csproj"],mappings="sync.json")\n'
put('BUILD.bazel', authored)
binding = dict(linuxWorker=True, useAppHost=False, generatedDirectories={'App/Generated': 'data'}, properties={'GeneratedValue':'first','LiteralProbe':'a+b <tag> 😀'}, documents={'App/App.csproj':dict(sha256=hashlib.sha256(project.encode()).hexdigest(),targets=['WriteGenerated'],tasks=[])})
def mapping():
    put('sync.json', json.dumps(dict(projects={'App/App.csproj':binding})))
cmd = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base=' + str(root / 'base'), '--ignore_all_rc_files']
def run(name, args, error=None):
    result = subprocess.run(cmd + args, cwd=w, text=True, capture_output=True)
    text = result.stdout + result.stderr
    if result.returncode:
        text += '\n'.join(p.read_text() for p in (w / 'bazel-bin').glob('*.diagnostics/build.log'))
    (root / (name + '.log')).write_text(text)
    assert result.returncode == 0 if error is None else result.returncode != 0 and error.lower() in text.lower(), text[-6000:]
    print(name, result.returncode, flush=True)
    return result.stdout
try:
    mapping(); run('sync', ['run', '//:sync'])
    put('BUILD.bazel', 'load(":projects.generated.bzl","app_projects")\n' + authored + 'app_projects()\n')
    assert run('worker', ['run', '//:App_App', '--jobs=2']).strip().splitlines()[-1] == 'first'
    binding['generatedDirectories'] = {}; mapping(); run('undeclared-sync', ['run', '//:sync'])
    run('undeclared-readonly', ['build', '//:App_App', '--jobs=2'], 'read-only')
    binding['generatedDirectories'] = {'App': 'data'}; mapping(); run('overlap-sync', ['run', '//:sync'])
    run('input-overlap', ['build', '//:App_App', '--jobs=2'], 'overlaps inputs')
    binding['generatedDirectories'] = {'App/Generated':'data'}; binding['properties']['GeneratedValue'] = 'second'
    mapping(); run('edit-sync', ['run', '//:sync'])
    assert run('edit', ['run', '//:App_App', '--jobs=2']).strip().splitlines()[-1] == 'second'
    binding['linuxWorker'] = False; mapping(); run('sandbox-sync', ['run', '//:sync'])
    assert run('sandbox', ['run', '//:App_App', '--jobs=2']).strip().splitlines()[-1] == 'second'
    binding['generatedDirectories'] = {'App/Generated':'App.dll'}; mapping(); run('collision-sync', ['run', '//:sync'])
    run('output-collision', ['build', '//:App_App', '--jobs=2'], 'conflicts with runtime output')
    binding['generatedDirectories'] = {'App/Generated':'data'}; mapping(); run('repair-sync', ['run', '//:sync'])
    assert run('repair', ['run', '//:App_App', '--jobs=2']).strip().splitlines()[-1] == 'second'
    run('check', ['run', '//:sync', '--', '--check'])
finally:
    subprocess.run(cmd + ['shutdown'], cwd=w, check=True)
