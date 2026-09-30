"""Bazel caches explicit Restore separately from body edits under linux-sandbox."""

import argparse
import contextlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import uuid

from qualify import DOTNET, ROOT, SDK, fixture, run


def actions(path):
    text = path.read_text()
    decoder = json.JSONDecoder()
    rows = []
    while text.strip():
        row, end = decoder.raw_decode(text.lstrip())
        text = text.lstrip()[end:]
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, help='Preserve a new disposable workspace and execution logs')
    parser.add_argument('--generated', action='store_true')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux'
    cache = os.environ['RULES_MSBUILD_PROJECT_CACHE_URL']
    with contextlib.nullcontext(str(args.directory)) if args.directory else tempfile.TemporaryDirectory(prefix='graph-bazel-preparation-') as temporary:
        base = Path(temporary).resolve()
        base.mkdir(parents=True, exist_ok=True)
        root = base / 'workspace'
        root.mkdir()
        contract = fixture(root)
        (root / 'Directory.Build.props').write_text('<Project><PropertyGroup><LangVersion>latest</LangVersion>'
            '</PropertyGroup><!-- ' + str(uuid.uuid4()) + ' --></Project>')
        shutil.copy(ROOT / 'global.json', root / 'global.json')
        contract['SharedInputs'].append('global.json')
        contract['Properties']['DisableTransitiveProjectReferences'] = 'true'
        outputs = [str(p.relative_to(root)) for p in root.glob('P*/obj/*') if p.is_file()]
        for i in range(3):
            project = contract['Projects'][f'P{i}/P{i}.csproj']
            project['Inputs'] = [p for p in project['Inputs'] if '/obj/' not in p]
            project['ReferenceBoundary'] = True
            project['DependencyCopies'] = {f'P{i}/bin/Release/net10.0/P{d}.{ext}': f'P{d}/bin/Release/net10.0/P{d}.{ext}'
                                           for d in range(i) for ext in ['dll', 'pdb']}
        restore_inputs = contract['SharedInputs'] + list(contract['Projects'])
        contract['Restore'] = {'Inputs': restore_inputs, 'Outputs': outputs}
        (root / 'contract.json').write_text(json.dumps(contract))
        sources = restore_inputs + [f'P{i}/Code.cs' for i in range(3)]
        (root / 'MODULE.bazel').write_text('module(name="graph_preparation")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n'
            f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})\n'
            'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
            'dotnet.sdk(name="dotnet",global_json="//:global.json")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
        (root / 'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph", "msbuild_graph_runner", "msbuild_graph_restore", "msbuild_graph_binary")\n'
            'msbuild_graph_runner(name="runner")\n'
            'msbuild_graph_restore(name="prepare",runner=":runner",contract="contract.json",linux_stable_paths=True,srcs=' + json.dumps(restore_inputs) + ')\n'
            'msbuild_graph(name="graph",runner=":runner",contract="contract.json",restore=":prepare",linux_stable_paths=True,srcs=' + json.dumps(sources) + ')\n'
            'msbuild_graph_binary(name="app",graph=":graph",assembly="P2/bin/Release/net10.0/P2.dll")\n')
        def sync():
            mapping = base / 'mapping.json'
            mapping.write_text(json.dumps({'projectDefaults': {'preparedRestore': True}}))
            run(DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root,
                SDK / 'sdk/10.0.400', 'P2/P2.csproj', '--graph', '--mappings', mapping)
        if args.generated:
            sync()
            (root / 'BUILD.bazel').write_text('load(":graph.generated.bzl", "app_graph")\n'
                'load("@rules_msbuild//msbuild:defs.bzl", "msbuild_graph_binary")\n'
                'app_graph(name="graph",linux_stable_paths=True)\n'
                'msbuild_graph_binary(name="app",graph=":graph",project="P2/P2.csproj")\n')
        for name, value, hits, prepare_runs in [('seed', 1, 0, 1), ('body', 2, 2, 0), ('props', 2, 0, 1)]:
            if name == 'body':
                (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; }')
            elif name == 'props':
                props = root / 'Directory.Build.props'
                props.write_text(props.read_text().replace('</PropertyGroup>', '<DefineConstants>RESTORE_REFRESH</DefineConstants></PropertyGroup>'))
            if args.generated and name == 'props':
                sync()
            execution = base / (name + '.execution.json')
            command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--batch', '--output_base=' + str(base / 'bazel'),
                'run', '//:app', '--spawn_strategy=linux-sandbox', '--jobs=2',
                '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + cache, '--execution_log_json_file=' + str(execution)]
            result = subprocess.run(command, cwd=root, env=dict(os.environ, USE_BAZEL_VERSION='9.2.0'), text=True, capture_output=True)
            assert result.returncode == 0, result.stdout + result.stderr
            assert result.stdout.strip().endswith(str(value)), result.stdout
            report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
            assert report['preparedRestore'] and report['hits'] == hits, report
            executed = [row for row in actions(execution) if row.get('mnemonic') == 'MSBuildGraphRestore' and not row.get('cacheHit')]
            assert len(executed) == prepare_runs, executed
            print(name, json.dumps(report), flush=True)
        print('PASS: native sandbox, cached Restore on body edits, configuration refresh and executable output')


if __name__ == '__main__':
    main()
