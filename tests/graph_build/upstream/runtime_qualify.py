"""Compare Linux managed-graph worker replay with fresh native-sandbox outputs.

An unused, declared fixture input forces graph execution without changing any
project fingerprint. These are correctness controls, not scored benchmarks.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path, help='new evidence directory')
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--versions', nargs='+', choices=['8.8.0', '9.2.0'], default=['9.2.0', '8.8.0'])
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    root = args.workspace.resolve()
    results = args.results.resolve()
    results.mkdir(parents=True, exist_ok=False)
    contract = json.loads((root / 'graph.generated.json').read_text())
    variants = [variant for project in contract['Projects'].values() for variant in project.get('Configurations') or [project]]
    directories = {directory for project in variants for directory in project['OutputDirectories']}
    files = {file for project in variants for file in project.get('OutputFiles', [])}
    count = sum(bool(project['OutputDirectories'] or project.get('OutputFiles')) for project in variants)
    # Only optional SDK resource state is omitted, as in GraphCache.OutputFiles.
    resource_states = {directory + '/' + Path(project).name + '.GenerateResource.cache'
                       for project, declaration in contract['Projects'].items()
                       for variant in declaration.get('Configurations') or [declaration]
                       for directory in variant['OutputDirectories'] if directory.startswith('artifacts/obj/')}
    rows = []

    def capture():
        artifact = root / 'bazel-bin/graph.graph'
        workspace = artifact / 'workspace'
        paths = {workspace / path for path in files} | {path for directory in directories for path in (workspace / directory).rglob('*')}
        outputs = {str(path.relative_to(workspace)): {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'mode': path.stat().st_mode & 0o777}
                   for path in paths if path.is_file() and not path.name.endswith('.AssemblyReference.cache')
                   and (str(path.relative_to(workspace)) not in resource_states or str(path.relative_to(workspace)) in files)}
        assert outputs, 'Missing graph outputs'
        return json.loads((artifact / 'report.json').read_text()), outputs

    def build(label, version, strategy):
        # Select the native rule as well as its Bazel strategy; merely changing
        # strategy still runs the worker adapter once when linux_worker is true.
        build_file.write_bytes(original_build if strategy == 'worker' else
                               original_build.replace(b'linux_worker=True', b'linux_worker=False'))
        output = args.output_base.resolve() / (version + '-' + strategy)
        env = dict(os.environ, USE_BAZEL_VERSION=version)
        env.pop('RULES_MSBUILD_PROJECT_CACHE_URL', None)
        env.pop('RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', None)
        command = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(output), 'build', '//:graph', '--jobs=4',
                   '--strategy=MSBuildGraph=' + strategy, '--spawn_strategy=linux-sandbox',
                   '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1']
        with (results / (label + '.log')).open('w') as log:
            subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        report, outputs = capture()
        assert report['preparedRestore'] == bool(contract.get('Restore'))
        assert report['readOnlyPreparedPackages'] == (bool(contract.get('Restore')) and strategy == 'worker')
        rows.append(dict(case=label, version=version, strategy=strategy, hits=report['hits'], misses=report['misses'], files=len(outputs)))
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        (results / (label + '.json')).write_text(json.dumps({'report': report, 'outputs': outputs}, indent=2) + '\n')
        print(json.dumps(rows[-1]), flush=True)
        return report, outputs

    def shutdown(version, strategy):
        output = args.output_base.resolve() / (version + '-' + strategy)
        if output.exists():
            subprocess.run([str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(output), 'shutdown'],
                           cwd=root, env=dict(os.environ, USE_BAZEL_VERSION=version),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    build_file = root / 'BUILD.bazel'
    original_build = build_file.read_bytes()
    assert original_build.count(b'linux_worker=True') == 1
    generated = root / 'graph.generated.bzl'
    original = generated.read_bytes()
    nonce = root / 'force-replay.txt'
    assert not nonce.exists(), 'Refusing to overwrite a source'
    text = original.decode()
    prefix, action = text.split('    msbuild_graph(\n')
    assert action.count('        srcs = [') == 1
    generated.write_text(prefix + '    msbuild_graph(\n' + action.replace('        srcs = [', '        srcs = ["force-replay.txt",', 1))
    baseline = None
    try:
        for version in args.versions:
            nonce.write_text('seed-' + version)
            report, outputs = build('seed-' + version, version, 'worker')
            assert report['hits'] == 0 and report['misses'] == count, report
            baseline = baseline or outputs
            assert outputs == baseline, 'Supported-version output parity failed'
            nonce.write_text('replay-' + version)
            report, outputs = build('replay-' + version, version, 'worker')
            assert report['hits'] == count and report['misses'] == 0, report
            assert outputs == baseline, 'Full local replay differs from seed'
            nonce.write_text('native-' + version)
            report, outputs = build('native-' + version, version, 'linux-sandbox')
            assert report['hits'] == 0 and report['misses'] == count, report
            assert outputs == baseline, 'Worker/native-sandbox output parity failed'
            shutdown(version, 'worker')
            shutdown(version, 'linux-sandbox')
    finally:
        build_file.write_bytes(original_build)
        generated.write_bytes(original)
        nonce.unlink(missing_ok=True)
        for version in args.versions:
            shutdown(version, 'worker')
            shutdown(version, 'linux-sandbox')
    print('PASS: complete replay and exact files/bytes/modes on supported versions')


if __name__ == '__main__':
    main()
