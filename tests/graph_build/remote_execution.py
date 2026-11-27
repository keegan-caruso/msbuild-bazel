"""Compare quickstart products from ordinary local and remote Linux actions."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[2]


def execution_records(path):
    decoder = json.JSONDecoder()
    data = path.read_text()
    offset = 0
    while offset < len(data):
        if data[offset].isspace():
            offset += 1
            continue
        record, offset = decoder.raw_decode(data, offset)
        yield record


def products(workspace):
    files = sorted(workspace.glob('*/bin/Release/**/*'))
    reference = 'Library/obj/Release/net11.0/ref/Library.dll'
    files.append(workspace / reference)
    manifest = {}
    for path in files:
        if path.is_file():
            manifest[path.relative_to(workspace).as_posix()] = [
                hashlib.sha256(path.read_bytes()).hexdigest(),
                stat.S_IMODE(path.stat().st_mode),
            ]
    for required in ('Library/bin/Release/net11.0/Library.dll', 'App/bin/Release/net11.0/App.dll',
                     'Tests/bin/Release/net11.0/Tests.dll', reference):
        if required not in manifest:
            raise ValueError(f'Missing qualification product: {required}')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='fresh directory for workspace, logs and receipts')
    parser.add_argument('--executor', required=True, help='REAPI endpoint of the pinned worker')
    parser.add_argument('--bazel', required=True, type=Path, help='Bazelisk or pinned Bazel executable')
    args = parser.parse_args()
    evidence = args.directory.resolve()
    bazel = args.bazel.resolve()
    evidence.mkdir(parents=True, exist_ok=False)
    client = evidence / 'client'
    shutil.copytree(ROOT / 'examples/quickstart', client, ignore=shutil.ignore_patterns('bazel-*', 'obj', 'bin'))
    module = client / 'MODULE.bazel'
    module.write_text(module.read_text().replace('"../msbuild-bazel"', json.dumps(str(ROOT))))
    source = client / 'Library/Message.cs'
    # Give repeated runs distinct action keys even against a shared executor.
    initial = '// RBE fixture ' + str(uuid.uuid4()) + '\n' + source.read_text()
    body = initial.replace('=> "Hello from MSBuild and Bazel"', '=> string.Concat("Hello from ", "MSBuild and Bazel")')
    api = body.replace('public static string Text()', 'public static int Revision => 2;\n    public static string Text()')
    assert initial != body != api
    previous = None
    remote_graph_keys = set()
    for phase, content in [('cold', initial), ('body', body), ('api', api)]:
        source.write_text(content)
        phase_products = {}
        for strategy in ('local', 'remote'):
            prefix = evidence / f'{phase}-{strategy}'
            log = prefix.with_suffix('.json')
            command = [str(bazel), '--ignore_all_rc_files', '--max_idle_secs=120', '--output_base=' + str(evidence / strategy),
                       'test', '//:tests', '--jobs=2', '--nocache_test_results', '--test_output=errors',
                       '--execution_log_json_file=' + str(log)]
            if strategy == 'remote':
                command += ['--remote_executor=' + args.executor, '--spawn_strategy=remote',
                            '--noremote_local_fallback', '--remote_download_outputs=all',
                            '--modify_execution_info=TestRunner=+no-remote-cache']
                if phase == 'cold':
                    command.append('--noremote_accept_cached')
            else:
                command.append('--spawn_strategy=sandboxed')
            with prefix.with_suffix('.log').open('w') as output:
                subprocess.run(command, cwd=client, stdout=output, stderr=subprocess.STDOUT, check=True, timeout=600)
            rows = [r for r in execution_records(log) if r['mnemonic'] in ('MSBuildGraph', 'TestRunner')]
            for mnemonic in ('MSBuildGraph', 'TestRunner'):
                matching = [r for r in rows if r['mnemonic'] == mnemonic]
                if not matching or any(r['cacheHit'] or (strategy == 'remote') != (r['runner'] == 'remote')
                                       or r.get('exitCode', 0) != 0 for r in matching):
                    raise ValueError(f'{prefix}: expected fresh {strategy} execution of {mnemonic}')
            if strategy == 'remote':
                key, = [r['digest']['hash'] for r in rows if r['mnemonic'] == 'MSBuildGraph']
                if not key or key in remote_graph_keys:
                    raise ValueError(f'{phase}: expected a distinct remote graph action digest')
                remote_graph_keys.add(key)
            manifest = products(client / 'bazel-bin/graph.graph/workspace')
            prefix.with_suffix('.products.json').write_text(json.dumps(manifest, indent=2) + '\n')
            phase_products[strategy] = manifest
        local, remote = phase_products['local'], phase_products['remote']
        differences = [p for p in sorted(local.keys() | remote.keys()) if local.get(p) != remote.get(p)]
        if differences:
            raise ValueError(f'{phase}: local and remote product bytes or modes differ: {differences}')
        implementation = remote['Library/bin/Release/net11.0/Library.dll'][0]
        reference = remote['Library/obj/Release/net11.0/ref/Library.dll'][0]
        if previous and (previous[0] == implementation or (previous[1] == reference) != (phase == 'body')):
            raise ValueError(f'{phase}: unexpected library implementation or reference invalidation')
        previous = implementation, reference
        print(f'PASS {phase}: {len(remote)} products; local and remote graph/test executed', flush=True)


if __name__ == '__main__':
    main()
