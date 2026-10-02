"""Create an SDK-style chain with explicit BUILD inputs and no NuGet downloads."""
import argparse
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from fixture_sdk import sdk_declarations

ROOT = Path(__file__).resolve().parents[1]


def prepare(output, count, linux_worker=False):
    if count < 2:
        raise ValueError('Use at least two projects')
    output.mkdir(parents=True, exist_ok=False)
    (output/'MODULE.bazel').write_text('''module(name="benchmark_fixture")
bazel_dep(name="rules_msbuild", version="0.0.0")
local_path_override(module_name="rules_msbuild", path=%s)
''' % json.dumps(str(ROOT)) + sdk_declarations())
    for i in range(count):
        folder = output/('P'+str(i)); folder.mkdir()
        reference = f'<ItemGroup><ProjectReference Include="../P{i-1}/P{i-1}.csproj" /></ItemGroup>' if i else ''
        resource = '<ItemGroup><EmbeddedResource Include="Message.txt" LogicalName="message" /></ItemGroup>' if i == 0 else ''
        if i == 0:
            (folder/'Message.txt').write_text('original')
        (folder/f'P{i}.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>'+reference+resource+'</Project>')
        (folder/'Value.cs').write_text(f'public static class P{i} {{ public static int Value() => '+(f'P{i-1}.Value()' if i else '1')+'; }')
    contract = dict(Version=1, Entry=f'P{count-1}/P{count-1}.csproj', SdkVersion='10.0.400', Properties={'Configuration':'Release'}, SharedInputs=[], Projects={})
    inputs = []
    for i in range(count):
        files = [f'P{i}/P{i}.csproj', f'P{i}/Value.cs'] + (['P0/Message.txt'] if i == 0 else [])
        inputs.extend(files)
        contract['Projects'][f'P{i}/P{i}.csproj'] = dict(Inputs=files, OutputDirectories=[f'P{i}/bin/Release/net10.0', f'P{i}/obj/Release/net10.0'])
    (output/'contract.json').write_text(json.dumps(contract, indent=2)+'\n')
    (output/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph","msbuild_graph_runner")\nmsbuild_graph_runner(name="runner")\nmsbuild_graph(name="benchmark",runner=":runner",contract="contract.json",srcs='+json.dumps(inputs)+(',linux_worker=True,linux_stable_paths=True' if linux_worker else '')+')\n')
    return output


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    p.add_argument('--projects', type=int, default=8)
    p.add_argument('--linux-worker', action='store_true')
    a = p.parse_args()
    prepare(a.output, a.projects, a.linux_worker)
