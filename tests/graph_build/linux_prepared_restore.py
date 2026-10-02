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
    parser.add_argument('--worker', action='store_true')
    parser.add_argument('--package', action='store_true', help='Include package assembly/build targets and reject package writes')
    parser.add_argument('--version', choices=['8.8.0', '9.2.0'], default='9.2.0')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux'
    assert not args.package or (args.worker and not args.generated), 'Package control uses the explicit worker fixture'
    cache = os.environ['RULES_MSBUILD_PROJECT_CACHE_URL']
    with contextlib.nullcontext(str(args.directory)) if args.directory else tempfile.TemporaryDirectory(prefix='graph-bazel-preparation-') as temporary, contextlib.ExitStack() as cleanup:
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
        package_source = None
        if args.package:
            package = base / 'package'
            package.mkdir()
            (package / 'Package.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                '<TargetFramework>net10.0</TargetFramework><PackageId>ReadOnly.Probe</PackageId></PropertyGroup>'
                '<ItemGroup><None Include="ReadOnly.Probe.targets" Pack="true" PackagePath="buildTransitive/" /></ItemGroup></Project>')
            (package / 'Code.cs').write_text('public static class PackageApi { public static int Value => 7; }')
            (package / 'ReadOnly.Probe.targets').write_text('<Project><Target Name="TryPackageWrite" BeforeTargets="CoreCompile" Condition="&apos;$(AttemptPackageWrite)&apos; == &apos;true&apos;">'
                '<WriteLinesToFile File="$(MSBuildThisFileDirectory)unexpected.txt" Lines="changed" Overwrite="true" /></Target></Project>')
            feed = root / '.package-source'
            feed.mkdir()
            run(DOTNET, 'pack', package / 'Package.csproj', '-c', 'Release', '-o', feed,
                '-p:Version=1.0.0', '-p:NuGetAudit=false', '-p:UseSharedCompilation=false')
            package_source = '.package-source/ReadOnly.Probe.1.0.0.nupkg'
            project = root / 'P0/P0.csproj'
            project.write_text(project.read_text().replace('</Project>', '<ItemGroup><PackageReference Include="ReadOnly.Probe" Version="1.0.0" /></ItemGroup></Project>'))
            (root / 'P0/PackageUse.cs').write_text('public static class PackageUse { public static int Value => PackageApi.Value; }')
            contract['Projects']['P0/P0.csproj']['Inputs'].append('P0/PackageUse.cs')
            contract['SharedInputs'].append(package_source)
        restore_inputs = contract['SharedInputs'] + list(contract['Projects'])
        contract['Restore'] = {'Inputs': restore_inputs, 'Outputs': outputs}
        (root / 'contract.json').write_text(json.dumps(contract))
        sources = restore_inputs + [f'P{i}/Code.cs' for i in range(3)] + (['P0/PackageUse.cs'] if args.package else [])
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
        if args.worker:
            build_file = root / 'BUILD.bazel'
            text = build_file.read_text()
            if args.generated:
                text = text.replace('app_graph(name="graph",linux_stable_paths=True)', 'app_graph(name="graph",linux_stable_paths=True,linux_worker=True)')
            else:
                text = text.replace('restore=":prepare",linux_stable_paths=True', 'restore=":prepare",linux_stable_paths=True,linux_worker=True')
            build_file.write_text(text)
        preparation_paths = None
        def worker_preparations():
            return set((Path(tempfile.gettempdir()) / ('rules-msbuild-workers-' + str(os.geteuid()))).glob('*/preparations/*/prepared/manifest.json'))
        before_preparations = worker_preparations()
        for name, value, hits, prepare_runs in [('seed', 1, 0, 1), ('body', 2, 2, 0), ('cache-config', 2, 3, 0), ('props', 2, 0, 1)]:
            if name == 'body':
                (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; }')
            elif name == 'props':
                props = root / 'Directory.Build.props'
                props.write_text(props.read_text().replace('</PropertyGroup>', '<DefineConstants>RESTORE_REFRESH</DefineConstants></PropertyGroup>'))
            if args.generated and name == 'props':
                sync()
            execution = base / (name + '.execution.json')
            command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(base / 'bazel'),
                'run', '//:app', '--spawn_strategy=linux-sandbox', '--jobs=2',
                '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + (cache + '/' if name == 'cache-config' else cache), '--execution_log_json_file=' + str(execution)]
            if name == 'seed':
                cleanup.callback(lambda: subprocess.run(command[:2] + ['shutdown'], cwd=root, env=dict(os.environ, USE_BAZEL_VERSION=args.version), capture_output=True))
            if args.worker:
                command += ['--strategy=MSBuildGraph=worker', '--worker_sandboxing']
            result = subprocess.run(command, cwd=root, env=dict(os.environ, USE_BAZEL_VERSION=args.version), text=True, capture_output=True)
            assert result.returncode == 0, result.stdout + result.stderr
            assert result.stdout.strip().endswith(str(value)), result.stdout
            report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
            assert report['preparedRestore'] and report['hits'] == hits, report
            if args.worker:
                assert report['readOnlyPreparedPackages'], report
                current = worker_preparations() - before_preparations
                if name == 'seed':
                    assert len(current) == 1, current
                    preparation_paths = current
                elif name == 'body':
                    assert current == preparation_paths, 'Bazel request did not reuse the existing private preparation'
                elif name == 'cache-config':
                    assert len(current) == 2 and preparation_paths <= current, current
                    preparation_paths = current
                else:
                    assert len(current) == len(preparation_paths) + 1 and preparation_paths <= current, current
            if args.package:
                assert (root / 'bazel-bin/graph.graph/workspace/P2/bin/Release/net10.0/Package.dll').is_file()
            executed = [row for row in actions(execution) if row.get('mnemonic') == 'MSBuildGraphRestore' and not row.get('cacheHit')]
            assert len(executed) == prepare_runs, (name, prepare_runs, [row['targetLabel'] for row in executed])
            print(name, json.dumps(report), flush=True)
        if args.package:
            props = root / 'Directory.Build.props'
            props.write_text(props.read_text().replace('</PropertyGroup>', '<AttemptPackageWrite>true</AttemptPackageWrite></PropertyGroup>'))
            result = subprocess.run(command, cwd=root, env=dict(os.environ, USE_BAZEL_VERSION=args.version), text=True, capture_output=True)
            assert result.returncode != 0 and 'Read-only file system' in result.stdout + result.stderr, result.stdout + result.stderr
        print('PASS: native sandbox, cached Restore on body edits, configuration refresh, executable output and selected package controls')


if __name__ == '__main__':
    main()
