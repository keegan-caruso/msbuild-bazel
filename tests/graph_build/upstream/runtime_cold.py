"""One matched cold-compilation control after the paired Pipelines scorecard.

SDK/package archives and expanded raw NuGet packages are available. Both engines
have fresh outputs; the graph broker has no local snapshots. This is a single
observation, distinct from SDK acquisition and repository/bootstrap setup.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('scorecard', type=Path, help='completed runtime_benchmark.py results')
    parser.add_argument('--output-base', type=Path, required=True, help='scorecard output base, stopped by its harness')
    parser.add_argument('--profile', action='store_true', help='separate diagnostic run, excluded from scored cold observations')
    parser.add_argument('--sample', type=int, default=1, help='positive observation index; preserves earlier results')
    args = parser.parse_args()
    assert args.sample >= 1
    root, evidence = args.workspace.resolve(), args.scorecard.resolve()
    assert not root.is_relative_to(evidence) and not evidence.is_relative_to(root)
    previous = json.loads((evidence / 'summary.json').read_text())
    assert any(row['case'] == 'api-summary' for row in previous['rows']), 'Complete incremental correctness first'
    name = 'cold-diagnostic' if args.profile else 'cold'
    destination = evidence / (name if args.sample == 1 else name + '-' + str(args.sample))
    destination.mkdir(exist_ok=False)
    raw, scratch = evidence / 'raw-workspace', evidence / 'raw-scratch'
    assert raw.is_dir() and scratch.is_dir()
    contract = json.loads((root / 'graph.generated.json').read_text())
    variants = [v for p in contract['Projects'].values() for v in p.get('Configurations') or [p]]
    directories = {p for v in variants for p in v['OutputDirectories']}
    files = {p for v in variants for p in v.get('OutputFiles', [])}
    inputs = set(contract['SharedInputs']) | {p for v in variants for p in v['Inputs']}
    assert not any(path.startswith('artifacts/obj/') for path in inputs), 'Do not remove declared restore inputs'
    sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
    stable, stable_sdk = '/__rules_msbuild_graph/output/workspace', '/__rules_msbuild_graph/sdk'
    raw_host = ['bash', str(ROOT / 'tests/graph_build/upstream/runtime_raw.sh'), str(sdk), str(raw), str(scratch)]
    common = ['-p:UseSharedCompilation=false', '-p:NetCoreSdkRoot=' + stable_sdk + '/sdk/' + contract['SdkVersion'],
              '-p:PathMap=' + stable + '=/_/workspace%2C' + stable_sdk + '=/_/sdk']
    properties = [f'-p:{k}={v}' for k, v in contract['Properties'].items()]
    environment = dict(os.environ, USE_BAZEL_VERSION='9.2.0')
    for name in ['RULES_MSBUILD_PROJECT_CACHE_URL', 'RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', 'RULES_MSBUILD_GRAPH_PROFILE']:
        environment.pop(name, None)
    bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(args.output_base.resolve())]
    build = root / 'BUILD.bazel'
    original_build = build.read_bytes()
    generated = root / 'graph.generated.bzl'
    original = generated.read_bytes()
    nonce = root / 'force-cold.txt'
    assert not nonce.exists()
    prefix, action = original.decode().split('    msbuild_graph(\n')
    assert action.count('        srcs = [') == 1
    config = raw / 'NuGet.Config'
    original_config = config.read_bytes() if config.exists() else None

    def execute(command, label, cwd):
        start = time.monotonic()
        with (destination / (label + '.log')).open('w') as log:
            subprocess.run(command, cwd=cwd, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        return time.monotonic() - start

    def capture(workspace):
        paths = {workspace / path for path in files} | {p for directory in directories for p in (workspace / directory).rglob('*')}
        return {str(p.relative_to(workspace)): {'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'mode': p.stat().st_mode & 0o777}
                for p in paths if p.is_file() and p.suffix in ['.dll', '.pdb', '.resources']
                and not (str(p.relative_to(workspace)).startswith('artifacts/obj/') and '/PreTrim/' in str(p.relative_to(workspace)))}

    try:
        if args.profile:
            assert original_build.count(b'linux_worker=True') == 1
            build.write_bytes(original_build.replace(b'linux_worker=True', b'linux_worker=True,profile_build=True'))
        # Stop any producer broker before forcing an otherwise identical action.
        execute(bazel + ['shutdown'], 'stop-producer', root)
        for directory in directories:
            shutil.rmtree(raw / directory, ignore_errors=True)
        for path in files:
            (raw / path).unlink(missing_ok=True)
        shutil.rmtree(raw / 'artifacts/obj', ignore_errors=True)
        config.write_text('<configuration><packageSources><clear/><add key="declared" value=".package-source"/></packageSources><fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>')
        restore = raw_host + ['restore', stable + '/' + contract['Entry'], '--configfile', stable + '/NuGet.Config',
                  '--source', stable + '/.package-source', '--packages', stable + '/.nuget', '-p:NuGetAudit=false',
                  '-p:NetCoreSdkRoot=' + stable_sdk + '/sdk/' + contract['SdkVersion']]
        restore += [f'-p:{k}={v}' for k, v in contract['Properties'].items() if k.lower() != 'targetframework']
        restore_seconds = execute(restore, 'raw-restore', raw)
        diagnostic = raw / '.qualification'
        diagnostic.mkdir(exist_ok=True)
        binlog = ['-bl:' + stable + '/.qualification/cold.binlog;ProjectImports=None'] if args.profile else []
        raw_seconds = execute(raw_host + ['msbuild', stable + '/' + contract['Entry'], '-graphBuild', '-m:4', '-t:Build', '-nologo', *common, *properties, *binlog], 'raw-build', raw)
        generated.write_text(prefix + '    msbuild_graph(\n' + action.replace('        srcs = [', '        srcs = ["force-cold.txt",', 1))
        nonce.write_text(str(time.time_ns()))
        seconds = execute(bazel + ['build', '//:graph', '--jobs=4', '--strategy=MSBuildGraph=worker', '--spawn_strategy=linux-sandbox',
                          '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1', '--disk_cache=', '--remote_cache=', '--noshow_progress',
                          '--build_event_json_file=' + str(destination / 'graph.bep')], 'graph-build', root)
        metrics = next(json.loads(line)['buildMetrics']['actionSummary'] for line in (destination / 'graph.bep').read_text().splitlines() if 'buildMetrics' in json.loads(line))
        actions = {r['mnemonic']: int(r.get('actionsExecuted', 0)) for r in metrics.get('actionData', [])}
        assert actions.get('MSBuildGraph') == 1, 'Cold must execute the graph action'
        report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
        assert report['hits'] == 0 and report['misses'] == 38, report
        if args.profile:
            assert report['operations'] and report['worker']
            shutil.copyfile(root / 'bazel-bin/graph.graph/report.binlog', destination / 'graph.binlog')
            shutil.copyfile(diagnostic / 'cold.binlog', destination / 'raw.binlog')
        else:
            assert report['operations'] is None and 'worker' not in report
        outputs = capture(root / 'bazel-bin/graph.graph/workspace')
        raw_outputs = capture(raw)
        assert outputs and {p: v['sha256'] for p, v in outputs.items()} == {p: v['sha256'] for p, v in raw_outputs.items()}, 'Cold byte parity failed'
        modes = dict(graph=dict(Counter(oct(v['mode']) for v in outputs.values())), raw=dict(Counter(oct(v['mode']) for v in raw_outputs.values())))
        row = dict(case='cold-compilation-diagnostic' if args.profile else 'cold-compilation', observations=1, sample=args.sample, actionsExecuted=actions, graphWallSeconds=seconds, rawRestoreSeconds=restore_seconds,
                   rawBuildSeconds=raw_seconds, rawWorkflowSeconds=restore_seconds + raw_seconds,
                   comparedDllPdbResourceFiles=len(outputs), observedFileModes=modes, runner=report,
                   scope='available SDK/packages; fresh outputs and empty project snapshots; warm Bazel repository/bootstrap state')
        (destination / 'summary.json').write_text(json.dumps(row, indent=2) + '\n')
        print(json.dumps(row), flush=True)
    finally:
        build.write_bytes(original_build)
        generated.write_bytes(original)
        nonce.unlink(missing_ok=True)
        if original_config is None:
            config.unlink(missing_ok=True)
        else:
            config.write_bytes(original_config)
        subprocess.run(bazel + ['shutdown'], cwd=root, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
