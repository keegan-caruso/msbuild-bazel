"""Compare classic/direct smoke staging with a declared retained SDK archive.

This measures consumer recovery only, without a source-production action. Run in
qualified Ubuntu ARM64 with RULES_MSBUILD_BAZEL set and an HTTP cache writable
for the two seed invocations. Measured invocations disable uploads and require
all non-test actions to hit. Every trial owns fresh workspace and Bazel roots.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import time

from source_action_recovery import actions, digest, profile_summary, runfiles_inventory


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def verify_archive_output(log, expected):
    data = log.read_text()
    decoder = json.JSONDecoder()
    hashes = []
    while data.strip():
        row, end = decoder.raw_decode(data.lstrip())
        data = data.lstrip()[end:]
        for output in row.get('actualOutputs', []):
            if output['path'].endswith('/sdk.generated/sdk.tar.gz'):
                hashes.append(output.get('digest', {}).get('hash'))
    require(hashes == [expected], 'Cached SDK output digest mismatch: ' + str(hashes))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--rules', type=Path, default=Path(__file__).resolve().parents[2],
                        help='Rules checkout to benchmark; may be an exported tree without Git')
    args = parser.parse_args()
    require(platform.system() == 'Linux' and platform.machine() == 'aarch64',
            'Run in qualified Ubuntu ARM64')
    archive = args.archive.resolve(strict=True)
    require(digest(archive) == args.sha256, 'SDK archive digest mismatch')
    root = args.directory.resolve()
    root.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(archive, root / 'sdk.tar.gz')
    archive = root / 'sdk.tar.gz'
    rules = args.rules.resolve(strict=True)
    layout = root / 'sdk-layout.bzl'
    shutil.copyfile(rules / 'tests/source_sdk/source_action.bzl', layout)
    revision = None
    try:
        result = subprocess.run(['git', '-C', str(rules), 'rev-parse', 'HEAD'],
                                capture_output=True, text=True, check=False)
        if result.returncode == 0:
            revision = result.stdout.strip()
    except FileNotFoundError:
        pass
    results = []
    seeds = [('classic', 8, 0, True), ('direct', 8, 0, True)]
    for mode, connections, pair, seed in seeds + [
            (mode, connections, pair, False) for pair in (1, 2, 3) for connections in ((1, 8) if pair != 2 else (8, 1))
            for mode in (('classic', 'direct') if pair != 2 else ('direct', 'classic'))]:
        trial = root / (f'seed-{mode}' if seed else f'c{connections}-p{pair}-{mode}')
        workspace = trial / 'workspace'
        workspace.mkdir(parents=True)
        os.link(archive, workspace / 'retained-sdk.tar.gz')
        shutil.copyfile(layout, workspace / 'source_action.bzl')
        (workspace / 'MODULE.bazel').write_text('module(name="source_sdk_action")\n'
            'bazel_dep(name="platforms",version="1.0.0")\n'
            'bazel_dep(name="rules_msbuild",version="0.0.0")\n'
            'local_path_override(module_name="rules_msbuild",path=' + json.dumps(str(rules)) + ')\n'
            'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
            'dotnet.sdk(name="controller",version="10.0.400",platforms=["linux-arm64"])\n'
            'use_repo(dotnet,"controller")\n'
            'register_toolchains("//:produced_registered","//:produced_runtime_registered")\n')
        (workspace / 'BUILD.bazel').write_text('load(":source_action.bzl","sdk_layout")\n'
            'load("@rules_msbuild//msbuild:sdk.bzl","msbuild_sdk")\n'
            'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph","msbuild_graph_runner","msbuild_graph_test")\n'
            'genrule(name="sdk",srcs=["retained-sdk.tar.gz"],outs=["sdk.generated/sdk.tar.gz"],cmd="cp $(location retained-sdk.tar.gz) $@")\n'
            'sdk_layout(name="layout",archive=":sdk")\n'
            'filegroup(name="dotnet",srcs=[":layout"],output_group="dotnet")\n'
            'msbuild_sdk(name="produced",dotnet=":dotnet",files=[":layout"],sdk_version="11.0.100",runtime_version="11.0.0",runtime_identifier="linux-arm64")\n'
            'msbuild_graph_runner(name="runner")\n'
            'msbuild_graph(name="graph",runner=":runner",contract="app-contract.json",srcs=["App.csproj","App.cs"],project_outputs={"App.csproj|net11.0":["bin/Release/net11.0","App.dll","Exe"]})\n'
            'msbuild_graph_test(name="smoke",graph=":graph",project="App.csproj",direct_executable_smoke=' + str(mode == 'direct') + ')\n')
        (workspace / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net11.0</TargetFramework><OutputType>Exe</OutputType><UseAppHost>false</UseAppHost><EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup><ItemGroup><Compile Include="App.cs" /></ItemGroup></Project>')
        (workspace / 'App.cs').write_text('System.Console.WriteLine("SDK_FROM_SOURCE="+System.Environment.Version); return System.Environment.Version.ToString()=="11.0.0" ? 0 : 1;')
        (workspace / 'app-contract.json').write_text(json.dumps(dict(Version=1,Entry='App.csproj',SdkVersion='11.0.100',Properties={'Configuration':'Release'},SharedInputs=[],Projects={'App.csproj':dict(Inputs=['App.csproj','App.cs'],OutputDirectories=['bin/Release/net11.0','obj/Release/net11.0'])})))
        log, trace = trial / 'execution.json', trial / 'profile.json'
        command = [
            os.environ['RULES_MSBUILD_BAZEL'], '--batch', '--host_jvm_args=-Xmx1024m',
            '--output_base=' + str(trial / 'base'),
            '--output_user_root=' + str(trial / 'user'),
            '--ignore_all_rc_files', 'test', '//:smoke', '--jobs=1', '--lockfile_mode=off',
            '--disk_cache=', '--remote_cache=' + args.cache,
            '--remote_upload_local_results=' + str(seed).lower(),
            '--remote_cache_async=false', '--remote_download_outputs=toplevel',
            '--remote_max_connections=' + str(connections),
            '--nocache_test_results', '--test_output=all',
            '--execution_log_json_file=' + str(log), '--profile=' + str(trace),
            '--generate_json_trace_profile', '--noslim_profile',
            '--experimental_profile_include_target_label',
        ]
        (trial / 'command.json').write_text(json.dumps(command, indent=2) + '\n')
        started = time.perf_counter()
        with (trial / 'build.log').open('w') as output:
            subprocess.run(command, cwd=workspace, stdout=output, stderr=subprocess.STDOUT, check=True, timeout=1800)
        elapsed = time.perf_counter() - started
        rows = actions(log, include_test_details=True)
        verify_archive_output(log, args.sha256)
        require('SDK_FROM_SOURCE=11.0.0' in (trial / 'build.log').read_text().splitlines(),
                'Smoke runtime identity mismatch: ' + str(trial))
        require(any(row['mnemonic'] == 'TestRunner' and not row['cacheHit'] and
                    row['commandArgs'][0].endswith('/test-setup.sh') for row in rows),
                'Smoke test did not execute: ' + str(trial))
        if not seed:
            require(all(row['cacheHit'] for row in rows if row['mnemonic'] != 'TestRunner'),
                    'Unexpected non-test execution: ' + str(rows))
            require(any(row['mnemonic'] == 'MSBuildGraph' and row['cacheHit'] for row in rows),
                    'No cached MSBuild graph: ' + str(trial))
        inventory = runfiles_inventory(rows, trial / 'runfiles.json')
        require(inventory['available'], 'Missing logical runfiles inventory: ' + str(trial))
        framework_roots = {path.split('/shared/')[0] for path in inventory['frameworkLayouts']}
        require(len(framework_roots) == (1 if mode == 'direct' else 2),
                'Unexpected logical framework roots: ' + str(inventory))
        result = dict(seed=seed, launcher=mode, connections=connections, pair=pair, seconds=elapsed, profile=profile_summary(trace), runfiles=inventory)
        results.append(result)
        (root / 'results.json').write_text(json.dumps(dict(sdkArchiveSha256=args.sha256, sdkLayoutSha256=digest(layout), rulesPath=str(rules), rulesRevision=revision, scope='retained SDK consumer; no SourceSdkBuild action', runs=results), indent=2) + '\n')
        print(json.dumps(result), flush=True)
        # Keep reports and inputs, release bulky disposable Bazel roots between trials.
        shutil.rmtree(trial / 'base')
        shutil.rmtree(trial / 'user')
    summary = {}
    for connections in (1, 8):
        ratios = []
        for pair in (1, 2, 3):
            times = {r['launcher']: r['seconds'] for r in results if not r['seed'] and r['connections'] == connections and r['pair'] == pair}
            ratios.append(times['classic'] / times['direct'])
        summary[str(connections)] = dict(pairedSpeedups=ratios, medianPairedSpeedup=statistics.median(ratios))
    def seconds(mode, connections, pair):
        return next(row['seconds'] for row in results if not row['seed'] and
                    row['launcher'] == mode and row['connections'] == connections and
                    row['pair'] == pair)

    summary['connectionPairedSpeedups'] = {
        mode: [seconds(mode, 1, pair) / seconds(mode, 8, pair) for pair in (1, 2, 3)]
        for mode in ('classic', 'direct')
    }
    (root / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
