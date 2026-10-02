"""Exercise the public graph build and executable-test rules as a consumer."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from qualify import ROOT, fixture


def main():
    with tempfile.TemporaryDirectory(prefix='generic-bazel-') as temporary:
        root = Path(temporary).resolve()
        startup = [str(ROOT / 'scripts/bazel-launcher.sh'), f'--output_base={root / "bazel"}']
        if '--linux-stable-paths' in sys.argv:
            startup.append('--batch')
        workspace = root / 'workspace'
        workspace.mkdir()
        contract = fixture(workspace)
        for project in contract['Projects'].values():
            project['Inputs'] = [p for p in project['Inputs'] if '/obj/' not in p]
        (workspace / 'contract.json').write_text(json.dumps(contract))
        shutil.copy(ROOT / 'global.json', workspace / 'global.json')
        contract['SharedInputs'].append('global.json')
        (workspace / 'contract.json').write_text(json.dumps(contract))
        (workspace / 'MODULE.bazel').write_text(
            'module(name="generic_graph")\n'
            'bazel_dep(name="rules_msbuild",version="0.0.0")\n'
            f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})\n'
            'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
            'dotnet.sdk(name="dotnet",global_json="//:global.json")\n'
            'use_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
        (workspace / 'BUILD.bazel').write_text(
            'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph","msbuild_graph_runner","msbuild_graph_test")\n'
            'msbuild_graph_runner(name="runner")\n'
            'msbuild_graph(name="app",runner=":runner",contract="contract.json",'
            'srcs=glob(["P*/*.cs","P*/*.csproj"])+["Directory.Build.props","global.json"])\n'
            'msbuild_graph_test(name="app_test",graph=":app",assembly="P2/bin/Release/net10.0/P2.dll")\n')
        if '--sync' in sys.argv:
            other = workspace / 'Other'
            other.mkdir()
            (other / 'Other.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup></Project>')
            (other / 'Code.cs').write_text('System.Console.WriteLine("other");')
            authored = ('load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\n'
                        'msbuild_sync(name="sync",mode="graph",projects=["P2/P2.csproj","Other/Other.csproj"])\n')
            (workspace / 'BUILD.bazel').write_text(authored)
            sync = startup + ['run', '//:sync']
            result = subprocess.run(sync, cwd=workspace, env=os.environ, text=True, capture_output=True)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            checked = subprocess.run(sync + ['--', '--check'], cwd=workspace, env=os.environ, text=True, capture_output=True)
            assert checked.returncode == 0, checked.stdout + checked.stderr
            (workspace / 'BUILD.bazel').write_text(authored +
                'load(":graph.generated.bzl","app_graph")\n'
                'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph_test","msbuild_graph_binary")\n'
                'app_graph(name="app")\n'
                'msbuild_graph_test(name="app_test",graph=":app",project="P2/P2.csproj")\n'
                'msbuild_graph_binary(name="run_app",graph=":app",project="P2/P2.csproj")\n')
        if '--publish' in sys.argv:
            assert '--sync' in sys.argv, '--publish requires --sync'
            build_file = workspace / 'BUILD.bazel'
            build_file.write_text(build_file.read_text().replace('app_graph(name="app")', 'app_graph(name="app",target="Publish")') +
                'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph_layout","msbuild_layout")\n'
                'msbuild_graph_layout(name="published",graph=":app",project="P2/P2.csproj")\n'
                'msbuild_layout(name="composed",paths={":published":"app"})\n')
        if '--linux-stable-paths' in sys.argv:
            build_file = workspace / 'BUILD.bazel'
            build_file.write_text(build_file.read_text().replace('name="app",', 'name="app",linux_stable_paths=True,').replace('app_graph(name="app")', 'app_graph(name="app",linux_stable_paths=True)'))
        command = startup + ['test', '//:app_test', '--test_output=errors']
        for expected in ('pass', 'fail'):
            if expected == 'fail':
                (workspace / 'P2/Code.cs').write_text('System.Environment.Exit(7);')
            result = subprocess.run(command, cwd=workspace, env=os.environ, text=True, capture_output=True)
            if (result.returncode == 0) != (expected == 'pass'):
                raise AssertionError(result.stdout + result.stderr)
            if expected == 'fail' and 'FAILED' not in result.stdout + result.stderr:
                raise AssertionError('Expected test failure, not build failure: ' + result.stdout + result.stderr)
        if '--sync' in sys.argv:
            (workspace / 'P2/Code.cs').write_text('System.Environment.Exit(P1.Value() == 1 ? 0 : 7);')
            def invoke(*arguments):
                result = subprocess.run(startup + list(arguments), cwd=workspace, env=os.environ, text=True, capture_output=True)
                assert result.returncode == 0, result.stdout + result.stderr
                return result.stdout + result.stderr
            invoke('run', '//:run_app')
            if '--publish' in sys.argv:
                invoke('build', '//:composed')
                layout = workspace / 'bazel-bin/composed.layout/app'
                assert all((layout / name).is_file() for name in ['P2.dll', 'P2.runtimeconfig.json', 'P1.dll', 'P0.dll'])

            runtime = workspace / 'bazel-bin/run_app.runtime'
            assert all(not path.is_symlink() for path in runtime.rglob('*'))
            invoke('test', '//:app_test')
            (workspace / 'Other/Code.cs').write_text('System.Console.WriteLine("changed unrelated app");')
            assert '(cached)' in invoke('test', '//:app_test')
            (workspace / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; }')
            failed = subprocess.run(command, cwd=workspace, env=os.environ, text=True, capture_output=True)
            assert failed.returncode != 0 and 'FAILED' in failed.stdout + failed.stderr
        if '--batch' not in startup:
            subprocess.run(startup + ['shutdown'], cwd=workspace, env=os.environ, check=True, capture_output=True)
        print('PASS: public graph action, executable test, source edit invalidates test result')


if __name__ == '__main__':
    main()
