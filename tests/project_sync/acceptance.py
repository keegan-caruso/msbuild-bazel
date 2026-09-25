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
sync = ['bash', str(ROOT / 'scripts/project-sync.sh'), str(workspace), 'App/App.csproj']
subprocess.run(sync, check=True)
bazel = os.environ.get('RULES_MSBUILD_BAZEL', str(ROOT / 'scripts/bazel-launcher.sh'))
command = [bazel, '--batch', '--output_user_root=' + str(root / 'user'), '--output_base=' + str(root / 'base'), 'run', '//:App_App']
for name, expected in [('initial', 'value=7'), ('props-edit', 'value=9')]:
    if name == 'props-edit':
        put('Shared.props', '<Project><PropertyGroup><Platform>x64</Platform><DefineConstants Condition="\'$(Platform)\' == \'AnyCPU\'">SECOND</DefineConstants></PropertyGroup></Project>')
    # This property edit changes compilation, not the generated source/dependency graph.
    subprocess.run(sync + ['--check'], check=True)
    result = subprocess.run(command, cwd=workspace, capture_output=True, text=True)
    (root / (name + '.log')).write_text(result.stdout + result.stderr)
    assert result.returncode == 0 and expected in result.stdout, (name, result.stdout, result.stderr[-3000:])
print('Generated app and imported-property edit passed')
