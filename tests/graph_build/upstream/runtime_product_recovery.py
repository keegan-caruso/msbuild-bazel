"""Close source-runtime inputs and verify recovery with native Bazel build/test.

Stop the producer, relocate the closure to another worker, then build the app and
runtime package with an execution log. Tests must actually execute separately.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import socket
import sys

from runtime_complete_remote import ROOT, spawns
from runtime_jit_public_consumer import preparation_sources

sys.path.insert(0, str(ROOT/'scripts'))
from source_runtime.common import digest


def close(root, output):
    root, output = root.resolve(), output.resolve()
    contract = json.loads((root/'graph.generated.json').read_text())
    wanted = {'BUILD.bazel', 'MODULE.bazel', 'MODULE.bazel.lock', 'graph.generated.bzl',
        'graph.generated.json', 'nuget.lock.json', 'runtime-product.json', 'runtime_product.bzl',
        'runtime_product_test.py', 'source_repository.bzl', 'LICENSE.TXT', 'THIRD-PARTY-NOTICES.TXT'}
    wanted.update(contract['SharedInputs'])
    wanted.update(contract.get('DefinitionDigests', {}))
    wanted.update(contract.get('Restore', {}).get('Inputs', []))
    for declaration in contract['Projects'].values():
        for node in declaration.get('Configurations') or [declaration]:
            wanted.update(node['Inputs'])
    wanted.update(['app/contract.json', 'native/driver-contract.json', 'native/BUILD.bazel',
        'native/native_action.bzl', 'native/native_inputs.bzl', 'native/coreclr.sh',
        'native/libraries.sh', 'native/host.sh', 'libraries/BUILD.bazel', 'host/BUILD.bazel'])
    for directory, filename in [('app', 'contract.json'), ('native', 'driver-contract.json')]:
        extra = json.loads((root/directory/filename).read_text())
        wanted.update(directory+'/'+name for name in extra['SharedInputs'])
        for node in extra['Projects'].values():
            wanted.update(directory+'/'+name for name in node['Inputs'])
    trees = tuple(name+'/' for name in contract.get('InputTrees', {}))
    wanted = {name for name in wanted if not name.startswith(trees+('.nuget/', '.graph-tools/'))}
    publish_inputs(root, output, wanted)


def close_sync(root, output, query_base):
    root, output = root.resolve(), output.resolve()
    wanted = preparation_sources(root, query_base)
    wanted.update(['BUILD.bazel', 'MODULE.bazel', 'MODULE.bazel.lock', 'graph.generated.json', 'graph.generated.bzl'])
    publish_inputs(root, output, wanted)


def publish_inputs(root, output, wanted):
    if output.exists() or output.is_relative_to(root):
        raise ValueError('Use a fresh closure outside the producer workspace')
    for name in sorted(wanted):
        source = root/name
        if Path(name).is_absolute() or '..' in Path(name).parts or source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(root):
            raise ValueError('Closure input must be an independent workspace file: '+name)
        target = output/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    module = output/'MODULE.bazel'
    text = re.sub(r'local_path_override\(module_name="rules_msbuild",path="[^"]+"\)',
        'local_path_override(module_name="rules_msbuild",path="../rules")', module.read_text())
    # The producer's acquisition directory is not a consumer dependency.
    text = re.sub(r'"file:[^"]+",\s*', '', text)
    module.write_text(text)
    (output/'recovery-inputs.json').write_text(json.dumps({
        name: dict(sha256=digest(output/name), mode=(output/name).stat().st_mode & 0o777)
        for name in sorted(wanted)}, indent=2)+'\n')
    print('Closed', len(wanted), 'declared inputs; no build outputs or local caches')


def capture(root):
    runtime = root/'bazel-bin/app_source_runtime.layout'
    return dict(machine=socket.gethostname(), workspace=str(root),
        contractSha256=digest(root/'graph.generated.json'),
        archiveSha256=digest(root/'bazel-bin/runtime_package.tar.gz'),
        files={str(path.relative_to(runtime)): dict(sha256=digest(path), mode=path.stat().st_mode & 0o777)
            for path in sorted(runtime.rglob('*')) if path.is_file()})


def check(root, seed, actions, result):
    current = capture(root)
    expected = json.loads(seed.read_text())
    if current['machine'] == expected['machine'] or current['workspace'] == expected['workspace']:
        raise ValueError('Require an independent, relocated consumer with the producer stopped')
    for name in ['contractSha256', 'archiveSha256', 'files']:
        if current[name] != expected[name]:
            raise ValueError('Recovered product differs from producer: '+name)
    rows = spawns(actions)
    required = {'MSBuildGraph': 3, 'MSBuildGraphRestore': 1, 'RuntimeNative': 3, 'RuntimeNativeVersions': 1}
    for mnemonic, count in required.items():
        matches = [row for row in rows if row.get('mnemonic') == mnemonic]
        if len(matches) != count or not all(row.get('cacheHit') and row.get('runner') == 'remote cache hit' for row in matches):
            raise ValueError('Expected remote recovery for '+mnemonic+': '+str(matches))
    current['actions'] = [dict(mnemonic=row['mnemonic'], cacheHit=row.get('cacheHit', False), runner=row['runner']) for row in rows]
    current['scope'] = 'Independent Bazel action recovery; run app_test/runtime_test with --nocache_test_results separately'
    result.write_text(json.dumps(current, indent=2)+'\n')
    print('PASS: independent graph/Restore/native recovery; runtime bytes, modes and archive match')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['close', 'close-sync', 'seed', 'check'])
    parser.add_argument('workspace', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seed', type=Path)
    parser.add_argument('--actions', type=Path)
    parser.add_argument('--preparation-base', type=Path, help='fresh query base for close-sync authored membership')
    args = parser.parse_args()
    root = args.workspace.resolve()
    if args.phase == 'close':
        close(root, args.output.resolve())
    elif args.phase == 'close-sync':
        if args.preparation_base is None:
            parser.error('close-sync requires --preparation-base')
        close_sync(root, args.output, args.preparation_base)
    elif args.phase == 'seed':
        args.output.write_text(json.dumps(capture(root), indent=2)+'\n')
    elif args.seed is None or args.actions is None:
        parser.error('check requires --seed and --actions')
    else:
        check(root, args.seed, args.actions, args.output)


if __name__ == '__main__':
    main()
