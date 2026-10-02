"""Check source-host test caching and runtime-input invalidation without recompiling."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    args = parser.parse_args()
    assert os.uname().sysname == "Linux" and os.uname().machine == "aarch64", "Qualification requires Linux ARM64"
    root, results = args.workspace.resolve(), args.results.resolve()
    results.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[3]
    bazel = [str(repo / 'scripts/bazel-launcher.sh'), '--output_base=' + str(args.output_base.resolve()),
             'test', '//:runtime_probe_test', '--jobs=4', '--strategy=MSBuildGraph=worker',
 '--worker_max_instances=MSBuildGraph=1',
 '--worker_sandboxing', '--disk_cache=', '--remote_cache=',
             '--test_output=errors', '--noshow_progress']
    rows = []
    app = root / 'bazel-bin/runtime_probe_build.graph/workspace/bin/Release/net10.0/App.dll'
    expected = hashlib.sha256(app.read_bytes()).hexdigest()
    def run(label, success=True, cached=False):
        bep = results / (label + '.bep')
        with (results / (label + '.log')).open('w') as log:
            process = subprocess.run(bazel + ['--build_event_json_file=' + str(bep)], cwd=root,
                                     env=dict(os.environ, USE_BAZEL_VERSION='9.2.0'), stdout=log, stderr=subprocess.STDOUT)
        assert (process.returncode == 0) == success, label
        events = [json.loads(line) for line in bep.read_text().splitlines()]
        metrics = next(event['buildMetrics']['actionSummary'] for event in events if 'buildMetrics' in event)
        compilation = sum(int(item.get('actionsExecuted', 0)) for item in metrics.get('actionData', [])
                          if item['mnemonic'] in ['MSBuildGraph', 'RuntimeNative'])
        assert compilation == 0, (label, metrics)
        text = (results / (label + '.log')).read_text()
        observed_cached = '(cached)' in text
        if cached:
            assert observed_cached, label
        if not success:
            assert any(event.get('testSummary', {}).get('overallStatus') == 'FAILED' for event in events), text[-3000:]
        assert hashlib.sha256(app.read_bytes()).hexdigest() == expected
        rows.append(dict(case=label, passed=success, cached=observed_cached, compilerAndNativeActions=compilation, appSha256=expected))
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(rows[-1], flush=True)
    marker = root / 'runtime_probe/runtime-state.txt'
    original = marker.read_bytes()
    try:
        run('unchanged-cached', cached=True)
        marker.write_text('invalid')
        run('runtime-input-edit', success=False)
    finally:
        marker.write_bytes(original)
    run('restored-runtime')


if __name__ == '__main__':
    main()
