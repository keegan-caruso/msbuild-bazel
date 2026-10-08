"""Seed or independently recover the graph-built source runtime through Bazel HTTP cache."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--cache-url', required=True)
    parser.add_argument('--phase', choices=['producer', 'consumer'], required=True)
    parser.add_argument('--seed-evidence', type=Path)
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert (args.phase == 'consumer') == (args.seed_evidence is not None)
    root, results, base = args.workspace.resolve(), args.results.resolve(), args.output_base.resolve()
    assert not base.exists() and not results.is_relative_to(root) and not root.is_relative_to(results)
    contract = json.loads((root / 'graph.generated.json').read_text())
    count = sum(bool(node['OutputDirectories'] or node.get('OutputFiles')) for project in contract['Projects'].values()
                for node in project.get('Configurations') or [project])
    assert contract['SdkVersion'] == '10.0.400' and count == 263
    manifest = json.loads((root / 'application.json').read_text())
    assert len(manifest['managed']) == 58 and len(manifest['native']) == 8 and manifest['framework'] == '10.0.0'
    results.mkdir(parents=True, exist_ok=False)
    environment = dict(os.environ, USE_BAZEL_VERSION='9.3.0')
    environment.pop('RULES_MSBUILD_GRAPH_PROFILE', None)
    environment.pop('RULES_MSBUILD_PROJECT_CACHE_URL', None)
    environment.pop('RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', None)
    bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(base)]
    def invoke(arguments, label):
        start = time.monotonic()
        with (results / (label + '.log')).open('w') as log:
            subprocess.run(bazel + arguments, cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        return time.monotonic() - start
    def capture():
        trees = ['graph.graph/workspace', 'app_build.graph/workspace', 'app_source_runtime.layout',
                 'app.runtime', 'app_test.runtime']
        trees += [name + '/runtime.generated' for name in ['native', 'native_support', 'host', 'crypto', 'compression']]
        files = {}
        for tree in trees:
            directory = root / 'bazel-bin' / tree
            assert directory.is_dir(), tree
            for path in directory.rglob('*'):
                if path.is_file():
                    assert not path.is_symlink(), path
                    files[tree + '/' + str(path.relative_to(directory))] = dict(
                        sha256=hashlib.sha256(path.read_bytes()).hexdigest(), mode=path.stat().st_mode & 0o777)
        assert files
        return files
    try:
        events = results / 'build.bep'
        options = ['--jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing',
                   '--worker_max_instances=MSBuildGraph=1', '--disk_cache=', '--remote_cache=' + args.cache_url,
                   '--remote_download_outputs=all', '--test_output=errors', '--noshow_progress',
                   '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + args.cache_url,
                   '--build_event_json_file=' + str(events)]
        options += ['--remote_upload_local_results=' + ('true' if args.phase == 'producer' else 'false')]
        seconds = invoke(['test', '//:app', '//:app_test', *options], 'build')
        records = [json.loads(line) for line in events.read_text().splitlines()]
        metrics = next(event['buildMetrics']['actionSummary'] for event in records if 'buildMetrics' in event)
        actions = {item['mnemonic']: int(item.get('actionsExecuted', 0)) for item in metrics.get('actionData', [])}
        runners = {item['name']: int(item['count']) for item in metrics['runnerCount'] if item['name'] != 'total'}
        executed = sum(count for name, count in runners.items() if name not in ['internal', 'remote cache hit'])
        files = capture()
        if args.phase == 'consumer':
            seed = json.loads(args.seed_evidence.read_text())
            assert seed['externalWorkspace'] != str(root), 'Use a relocated independent consumer with the producer stopped'
            assert files == seed['files'], 'Recovered source-runtime outputs differ'
            # actionsExecuted includes remote cache completions. Only internal
            # bookkeeping and remote-cache runners may complete consumer actions.
            assert runners.get('remote cache hit', 0) > 0 and executed == 0, runners
        verification = results / 'verification.json'
        with (results / 'verification.log').open('w') as log:
            subprocess.run(['python3', str(Path(__file__).with_name('runtime_application_verify.py')), str(root), str(verification)],
                           cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        outcome = json.loads(verification.read_text())
        if args.phase == 'consumer':
            assert outcome['binaryHashes'] == seed['verification']['binaryHashes']
            assert outcome['sdkAbsentLoadedSourceComponents'] == seed['verification']['sdkAbsentLoadedSourceComponents']
        report = dict(phase=args.phase, version='9.3.0', externalWorkspace=str(root), seconds=seconds,
                      actions=actions, runners=runners, executedSpawns=executed, files=files, verification=outcome,
                      scope='whole Bazel action-cache correctness; construction/acquisition included; not project-cache timing or RBE')
        (results / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({key: value for key, value in report.items() if key not in ['files', 'verification']}), flush=True)
        print('PASS: source-runtime ' + args.phase + ' action-cache and SDK-absent execution', flush=True)
    finally:
        subprocess.run(bazel + ['shutdown'], cwd=root, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
