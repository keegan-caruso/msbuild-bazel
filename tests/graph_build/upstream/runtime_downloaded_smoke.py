"""Bazel-test an ordinary downloaded-SDK app consuming the runtime graph's DLL."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
PRODUCT = 'artifacts/bin/System.IO.Pipelines/Release/net10.0/System.IO.Pipelines.dll'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime_workspace', type=Path)
    parser.add_argument('output', type=Path, help='fresh owned app workspace')
    parser.add_argument('--cache-url', required=True)
    args = parser.parse_args()
    runtime = args.runtime_workspace.resolve()
    digest = hashlib.sha256((runtime / 'bazel-bin/graph.graph/workspace' / PRODUCT).read_bytes()).hexdigest().upper()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    (root / 'MODULE.bazel').write_text('module(name="runtime_consumer_smoke")\n'
        'bazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path=' + json.dumps(str(ROOT)) + ')\n'
        'bazel_dep(name="runtime_downloaded_workflow",version="0.0.0")\nlocal_path_override(module_name="runtime_downloaded_workflow",path=' + json.dumps(str(runtime)) + ')\n'
        'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
    (root / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup>'
        '<ItemGroup><Reference Include="System.IO.Pipelines" HintPath="inputs/System.IO.Pipelines.dll"/></ItemGroup></Project>')
    (root / 'NuGet.Config').write_text('<configuration><packageSources><clear/></packageSources></configuration>')
    (root / 'Program.cs').write_text('''using System;
using System.IO;
using System.IO.Pipelines;
using System.Security.Cryptography;

var hash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(Pipe).Assembly.Location)));
if (hash != Environment.GetEnvironmentVariable("EXPECTED_PIPELINES_SHA256")) return 1;
var pipe = new Pipe();
var memory = pipe.Writer.GetMemory(1);
memory.Span[0] = 42;
pipe.Writer.Advance(1);
await pipe.Writer.FlushAsync();
pipe.Writer.Complete();
var read = await pipe.Reader.ReadAsync();
if (read.Buffer.Length != 1 || read.Buffer.FirstSpan[0] != 42) return 2;
pipe.Reader.AdvanceTo(read.Buffer.End);
pipe.Reader.Complete();
Console.WriteLine("PASS: downloaded SDK runs the exact source-built Pipelines assembly");
return 0;
''')
    build = ('load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\n'
             'msbuild_sync(name="sync",projects=["App.csproj"],inputs={"@runtime_downloaded_workflow//:pipelines_assembly":"inputs/System.IO.Pipelines.dll"})\n')
    (root / 'BUILD.bazel').write_text(build)
    base = root.parent / (root.name + '-bazel')
    assert not base.exists()
    command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(base)]
    options = ['--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + args.cache_url, '--jobs=4',
               '--strategy=MSBuildGraph=worker', '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1', '--remote_cache=', '--disk_cache=']
    if os.environ.get('RULES_MSBUILD_TEST_REPOSITORY_CACHE'):
        options += ['--repository_cache=' + os.environ['RULES_MSBUILD_TEST_REPOSITORY_CACHE']]
    try:
        with (root / 'sync.log').open('w') as log:
            subprocess.run(command + ['run', '//:sync', *options], cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
        (root / 'BUILD.bazel').write_text(build + 'load(":graph.generated.bzl","app_graph")\n'
            'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph_test")\n'
            'app_graph(name="graph",linux_worker=True,linux_stable_paths=True)\n'
            'msbuild_graph_test(name="test",graph=":graph",project="App.csproj",env={"EXPECTED_PIPELINES_SHA256":' + json.dumps(digest) + '})\n')
        with (root / 'test.log').open('w') as log:
            subprocess.run(command + ['test', '//:test', *options, '--nocache_test_results', '--test_output=all'], cwd=root,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        print('PASS: Bazel test loaded the exact source-built Pipelines DLL on the downloaded SDK host', flush=True)
    finally:
        subprocess.run(command + ['shutdown'], cwd=root, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
