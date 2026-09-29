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
            authored = ('load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\n'
                        'msbuild_sync(name="sync",projects=["P2/P2.csproj"])\n')
            (workspace / 'BUILD.bazel').write_text(authored)
            sync = [str(ROOT / 'scripts/bazel-launcher.sh'), f'--output_base={root / "bazel"}',
                    'run', '//:sync', '--', '--graph']
            result = subprocess.run(sync, cwd=workspace, env=os.environ, text=True, capture_output=True)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
            (workspace / 'BUILD.bazel').write_text(authored +
                'load(":graph.generated.bzl","app_graph")\n'
                'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph_test")\n'
                'app_graph(name="app")\n'
                'msbuild_graph_test(name="app_test",graph=":app",assembly="P2/bin/Release/net10.0/P2.dll")\n')
        command = [str(ROOT / 'scripts/bazel-launcher.sh'), f'--output_base={root / "bazel"}',
                   'test', '//:app_test', '--test_output=errors']
        for expected in ('pass', 'fail'):
            if expected == 'fail':
                (workspace / 'P2/Code.cs').write_text('System.Environment.Exit(7);')
            result = subprocess.run(command, cwd=workspace, env=os.environ, text=True, capture_output=True)
            if (result.returncode == 0) != (expected == 'pass'):
                raise AssertionError(result.stdout + result.stderr)
            if expected == 'fail' and 'FAILED' not in result.stdout + result.stderr:
                raise AssertionError('Expected test failure, not build failure: ' + result.stdout + result.stderr)
        print('PASS: public graph action, executable test, source edit invalidates test result')


if __name__ == '__main__':
    main()
