"""Public Bazel 8/9 actions share project snapshots across fresh output bases."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from qualify import DOTNET, ROOT, SDK, fixture, run


def main():
    assert os.uname().sysname == 'Linux'
    cache = os.environ['RULES_MSBUILD_PROJECT_CACHE_URL']
    with tempfile.TemporaryDirectory(prefix='graph-bazel-remote-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        fixture(root)
        with (root / 'Directory.Build.props').open('a') as stream:
            stream.write('<!-- ' + str(uuid.uuid4()) + ' -->')
        shutil.copy(ROOT / 'global.json', root / 'global.json')
        (root / 'MODULE.bazel').write_text('module(name="graph_remote")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n'
            f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})\n'
            'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
            'dotnet.sdk(name="dotnet",global_json="//:global.json")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
        run(DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root, SDK / 'sdk/10.0.400', 'P2/P2.csproj', '--graph')
        (root / 'BUILD.bazel').write_text('load(":graph.generated.bzl","app_graph")\n'
            'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph_binary")\n'
            'app_graph(name="graph",linux_stable_paths=True)\n'
            'msbuild_graph_binary(name="app",graph=":graph",project="P2/P2.csproj")\n')
        digests = []
        for version, hits, value in [('8.8.0', 0, 1), ('9.2.0', 3, 1), ('9.2.0', 2, 2)]:
            if value == 2:
                (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; }')
            output = base / ('bazel-' + version)
            command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--batch', '--output_base=' + str(output),
                       'run', '//:app', '--spawn_strategy=processwrapper-sandbox',
                       '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + cache]
            result = subprocess.run(command, cwd=root, env=dict(os.environ, USE_BAZEL_VERSION=version), text=True, capture_output=True)
            assert result.returncode == 0, result.stdout + result.stderr
            assert result.stdout.strip().endswith(str(value)), result.stdout
            report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
            assert report['hits'] == hits and report['misses'] == 3 - hits, report
            payload = next((output / 'execroot/_main/bazel-out').glob('*-exec*/bin/graph_runner.runner/GraphBuild.dll'))
            digests.append(hashlib.sha256(payload.read_bytes()).hexdigest())
            print(version, value, json.dumps(report), flush=True)
        assert len(set(digests)) == 1, 'Runner identity must not depend on bootstrap output paths'
        print('PASS: Bazel 8/9 bootstrap identity, remote replay and body-edit reuse')


if __name__ == '__main__':
    main()
