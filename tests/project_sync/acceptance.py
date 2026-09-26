"""Generate, build and run a props-based app, then change an imported property."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output', type=Path)
a = p.parse_args()
root = a.output.resolve()
root.mkdir(parents=True, exist_ok=False)
workspace = root / 'workspace'
workspace.mkdir()


def put(path, text):
    target = workspace / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)


put('Directory.Build.props', '<Project><Import Project="Shared.props"/><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
put('Shared.props', '<Project><PropertyGroup><Platform>x64</Platform><DefineConstants Condition="\'$(Platform)\' == \'AnyCPU\'">FIRST</DefineConstants></PropertyGroup></Project>')
put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"/>')
put('Core/Core.cs', '''public static class Core { public static int Value =>
#if FIRST
7;
#else
9;
#endif
}
''')
put('App/App.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Core/Core.csproj"/></ItemGroup></Project>')
put('App/Program.cs', 'System.Console.WriteLine("value=" + Core.Value);')
put('MODULE.bazel', '''module(name="project_sync_acceptance")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path=''' + json.dumps(str(ROOT)) + ''')
dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")
dotnet.sdk(name="dotnet",version="10.0.400")
use_repo(dotnet,"dotnet")
register_toolchains("@dotnet//:all")
''')
authored = 'load("@rules_msbuild//msbuild:sync.bzl", "msbuild_sync")\nmsbuild_sync(name="sync", projects=["App/App.csproj"])\n'
put('BUILD.bazel', authored)
bazel = os.environ.get('RULES_MSBUILD_BAZEL', str(ROOT / 'scripts/bazel-launcher.sh'))
startup = [bazel, '--output_user_root=' + str(root / 'user'), '--output_base=' + str(root / 'base')]
# Exercise the app-facing interface with no installed dotnet on PATH.
env = {k:v for k,v in os.environ.items() if not k.startswith(('DOTNET', 'MSBuild', 'MSBUILD')) and k not in ['RULES_MSBUILD_DOTNET_ROOT', 'NUGET_PACKAGES']}
env['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'


def run(name, args, expected=None, success=True):
    result = subprocess.run(startup + args, cwd=workspace, env=env, capture_output=True, text=True)
    (root / (name + '.log')).write_text(result.stdout + result.stderr)
    assert (result.returncode == 0) == success, (name, result.stdout, result.stderr[-3000:])
    if expected:
        assert expected in result.stdout + result.stderr, (name, result.stdout, result.stderr[-3000:])


try:
    run('bootstrap', ['run', '//:sync'])
    assert (workspace / 'BUILD.bazel').read_text() == authored
    authored = 'load(":projects.generated.bzl", "app_projects")\n' + authored + 'app_projects()\n'
    put('BUILD.bazel', authored)
    for name, expected in [('initial', 'value=7'), ('props-edit', 'value=9')]:
        if name == 'props-edit':
            put('Shared.props', '<Project><PropertyGroup><Platform>x64</Platform><DefineConstants Condition="\'$(Platform)\' == \'AnyCPU\'">SECOND</DefineConstants></PropertyGroup></Project>')
        run(name + '-check', ['run', '//:sync', '--', '--check'])
        run(name, ['run', '//:App_App'], expected)
    # A configured Platform must agree between evaluation and compilation.
    put('sync.json', json.dumps({'projectDefaults': {'platform': 'arm64'}}))
    authored = authored.replace('projects=["App/App.csproj"])', 'projects=["App/App.csproj"], mappings="sync.json")')
    put('BUILD.bazel', authored)
    put('Shared.props', '<Project><PropertyGroup><DefineConstants Condition="\'$(Platform)\' == \'arm64\'">FIRST</DefineConstants></PropertyGroup></Project>')
    run('platform-sync', ['run', '//:sync'])
    run('platform-app', ['run', '//:App_App'], 'value=7')
    original = (workspace / 'projects.generated.bzl').read_bytes()
    put('Core/Added.cs', 'public class Added {}')
    run('stale', ['run', '//:sync', '--', '--check'], 'stale', success=False)
    assert (workspace / 'projects.generated.bzl').read_bytes() == original
    run('resync', ['run', '//:sync'])
    assert 'Core/Added.cs' in (workspace / 'projects.generated.bzl').read_text()
    assert (workspace / 'BUILD.bazel').read_text() == authored
    run('resynced-app', ['run', '//:App_App'], 'value=7')
finally:
    subprocess.run(startup + ['shutdown'], cwd=workspace, env=env, check=True)
print('Bazel sync bootstrap, check, props edit, stale source, resync and app execution passed')
