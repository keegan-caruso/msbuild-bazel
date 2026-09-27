"""Create an SDK-style chain with explicit BUILD inputs and no NuGet downloads."""
import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(output, count):
    if count < 2:
        raise ValueError('Use at least two projects')
    output.mkdir(parents=True, exist_ok=False)
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
    (output/'MODULE.bazel').write_text('''module(name="benchmark_fixture")
bazel_dep(name="rules_msbuild", version="0.0.0")
local_path_override(module_name="rules_msbuild", path=%s)
dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")
dotnet.sdk(name="dotnet",version="10.0.400")
use_repo(dotnet,"dotnet")
register_toolchains("@dotnet//:all")
''' % (json.dumps(str(ROOT))))
    (output/'BUILD.bazel').write_text('''alias(name="benchmark",actual="//P%d")
''' % (count - 1))
    for i in range(count):
        folder = output/('P'+str(i)); folder.mkdir()
        reference = f'<ItemGroup><ProjectReference Include="../P{i-1}/P{i-1}.csproj" /></ItemGroup>' if i else ''
        resource = '<ItemGroup><EmbeddedResource Include="Message.txt" LogicalName="message" /></ItemGroup>' if i == 0 else ''
        if i == 0:
            (folder/'Message.txt').write_text('original')
        (folder/f'P{i}.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>'+reference+resource+'</Project>')
        (folder/'Value.cs').write_text(f'public static class P{i} {{ public static int Value() => '+(f'P{i-1}.Value()' if i else '1')+'; }')
        build = 'load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_items")\n'
        build += 'msbuild_library(name="P%d",project="P%d.csproj",target_framework="net10.0",srcs=["Value.cs"],deps=%s,items=%s,visibility=["//visibility:public"])\n' % (i, i, json.dumps([f'//P{i-1}'] if i else []), json.dumps([":message"] if i == 0 else []))
        if i == 0:
            build += 'msbuild_items(name="message",item_type="EmbeddedResource",srcs=["Message.txt"],metadata={"LogicalName":"message"})\n'
        (folder/'BUILD.bazel').write_text(build)
    return output


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('output', type=Path)
    p.add_argument('--projects', type=int, default=8)
    a = p.parse_args()
    prepare(a.output, a.projects)
