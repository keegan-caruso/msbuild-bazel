"""Public graph workers keep snapshots, isolate requests and recover after failure."""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from qualify import DOTNET, ROOT, SDK, fixture, run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bazel-version', default='9.2.0', choices=['8.8.0', '9.2.0'])
    parser.add_argument('--cache-mb', type=int, default=4096)
    args = parser.parse_args()
    reused = 2 if args.cache_mb else 0
    assert os.uname().sysname == 'Linux'
    with tempfile.TemporaryDirectory(prefix='graph-worker-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        fixture(root)
        shutil.copy(ROOT / 'global.json', root / 'global.json')
        (root / 'MODULE.bazel').write_text('module(name="graph_worker")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n'
            f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})\n'
            'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
            'dotnet.sdk(name="dotnet",global_json="//:global.json")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
        run(DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root, SDK / 'sdk/10.0.400', 'P2/P2.csproj', '--graph')
        (root / 'BUILD.bazel').write_text('load(":graph.generated.bzl","app_graph")\n'
            'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph_binary")\n'
            f'app_graph(name="graph",linux_stable_paths=True,linux_worker=True,worker_cache_mb={args.cache_mb})\n'
            'msbuild_graph_binary(name="app",graph=":graph",project="P2/P2.csproj")\n')
        command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(base / 'bazel')]
        env = dict(os.environ, USE_BAZEL_VERSION=args.bazel_version)
        env.pop('RULES_MSBUILD_PROJECT_CACHE_URL', None)
        env.pop('RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', None)
        rows = []

        def build(label, value, hits=None, strategy='worker', success=True, error='error CS'):
            result = subprocess.run(command + ['run', '//:app', '--strategy=MSBuildGraph=' + strategy,
                '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1', '--worker_verbose'],
                cwd=root, env=env, text=True, capture_output=True)
            assert (result.returncode == 0) == success, result.stdout + result.stderr
            if not success:
                assert error in result.stderr + result.stdout, result.stderr
                return
            assert result.stdout.strip().endswith(str(value)), result.stdout
            report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
            if hits is not None:
                assert report['hits'] == hits, report
            rows.append(dict(case=label, hits=report['hits'], misses=report['misses']))
            print(json.dumps(rows[-1]), flush=True)
            return {str(path.relative_to(root / 'bazel-bin/graph.graph/workspace')): path.read_bytes()
                    for path in (root / 'bazel-bin/graph.graph/workspace').rglob('*')
                    if path.is_file() and path.suffix in ('.dll', '.pdb', '.json')}

        try:
            build('seed', 1, 0)
            source = root / 'P0/Code.cs'
            source.write_text('public class P0 { public static int Value() => 2; }')
            worker_outputs = build('body', 2, reused)
            source.write_text('this is invalid C#')
            build('failure', None, success=False)
            source.write_text('public class P0 { public static int Value() => 3; }')
            build('after-failure', 3, reused)
            # A changed declared property invalidates the complete graph.
            props = root / 'Directory.Build.props'
            props.write_text(props.read_text().replace('latest', 'preview'))
            build('stale-definition', None, success=False, error='Graph definition changed')
            run(DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root, SDK / 'sdk/10.0.400', 'P2/P2.csproj', '--graph')
            build('property', 3, 0)
            # Restore the body case, stop the broker, and force a fresh native
            # action. Its compared outputs must match the worker's result.
            props.write_text(props.read_text().replace('preview', 'latest'))
            source.write_text('public class P0 { public static int Value() => 2; }')
            run(DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root, SDK / 'sdk/10.0.400', 'P2/P2.csproj', '--graph')
            subprocess.run(command + ['shutdown'], cwd=root, env=env, check=True, capture_output=True)
            subprocess.run(command + ['clean'], cwd=root, env=env, check=True, capture_output=True)
            fresh_outputs = build('native-control', 2, 0, strategy='linux-sandbox')
            assert worker_outputs == fresh_outputs, 'Worker/native output parity failed'
            print('PASS: ' + args.bazel_version + ' sandboxed worker reuse, failure recovery, property invalidation and fresh native parity')
        finally:
            subprocess.run(command + ['shutdown'], cwd=root, env=env, capture_output=True)


if __name__ == '__main__':
    main()
