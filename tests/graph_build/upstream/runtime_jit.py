"""Qualify unchanged Add1_ro, its generator, and source-runtime execution.

Producer extends the qualified runtime workspace; --raw verifies compiled-byte
parity. Consumer uses a fresh workspace/base and a stopped producer. Its refs and
CORE_ROOT are digest-locked declared producer artifacts, so this recovery control
covers the three test/dependency compilation projects, not another 481-node runtime build.
"""
import argparse
import ast
import hashlib
import json
import os
import shutil
from pathlib import Path
import subprocess
import tarfile
import time
import uuid

from runtime_jit_prepare import CODE, ENTRY, PINNED, TEST_OUTPUT

ROOT = Path(__file__).resolve().parents[3]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    return {str(p.relative_to(root)): dict(sha256=digest(p), mode=p.stat().st_mode & 0o777)
            for p in sorted(root.rglob('*')) if p.is_file() and not p.name.endswith('.AssemblyReference.cache')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--phase', choices=['producer', 'consumer'], required=True)
    parser.add_argument('--raw', type=Path)
    parser.add_argument('--reuse-producer-cache', action='store_true', help='repeat producer controls from already published snapshots; default requires all misses')
    parser.add_argument('--seed-report', type=Path)
    parser.add_argument('--trim-between-rows', action='store_true', help='trim released guest blocks outside invocations')
    parser.add_argument('--host-space-path', type=Path, help='host bind mount; require 8 GiB free before each invocation')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert (args.phase == 'consumer') == bool(args.seed_report)
    assert not args.reuse_producer_cache or args.phase == 'producer'
    root, results = args.workspace.resolve(), args.results.resolve()
    results.mkdir(parents=True, exist_ok=False)
    for path, value in PINNED.items():
        assert digest(root / path) == value, path
    build = root / 'BUILD.bazel'
    original_build = build.read_text()
    source = root / CODE
    original = source.read_bytes()
    endpoint = os.environ['RULES_MSBUILD_PROJECT_CACHE_URL']
    bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(args.output_base.resolve())]
    options = ['--jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing',
               '--worker_max_instances=MSBuildGraph=1', '--disk_cache=', '--remote_cache=',
               '--strategy=RuntimeNative=standalone', '--nocache_test_results', '--test_output=all',
               '--lockfile_mode=off', '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + endpoint]

    def check_space():
        if args.trim_between_rows:
            subprocess.run(['fstrim', '/'], check=True, capture_output=True)
        if args.host_space_path:
            disk = os.statvfs(args.host_space_path)
            assert disk.f_bavail * disk.f_frsize >= 8 * 1024**3, 'Insufficient host disk headroom'

    check_space()
    products = root / 'source-products.tar.gz'
    if args.seed_report:
        expected = json.loads(args.seed_report.read_text())
        assert digest(products) == expected['sourceProductsSha256'], 'Source products changed'
    else:
        # Materialize source-built producer edges through normal HTTP caching.
        # Runtime preparation is separate from this three-project recovery.
        preparation = [p for p in options if p not in ['--nocache_test_results', '--test_output=all']]
        preparation += ['--remote_cache=' + endpoint, '--remote_cache_async=false', '--remote_download_outputs=all']
        with (results / 'source-products.log').open('w') as log:
            subprocess.run(bazel + ['build', '//:jit_refs', '//:jit_core_root', *preparation], cwd=root,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        with tarfile.open(products, 'w:gz') as archive:
            archive.add(root / 'bazel-bin/jit_refs/net10.0', arcname='references')
            archive.add(root / 'bazel-bin/jit_core_root.layout', arcname='core-root')
        expected = dict(sourceProductsSha256=digest(products))
    shutil.copyfile(Path(__file__).with_name('runtime_jit_artifacts.bzl'), root / 'runtime_jit_artifacts.bzl')
    lines = original_build.splitlines()
    if any(line.startswith("msbuild_graph_output(name='jit_refs'") for line in lines):
        replaced = 0
        for i, line in enumerate(lines):
            if line.startswith("msbuild_graph_output(name='jit_refs'") or line.startswith("msbuild_layout(name='jit_core_root'"):
                name, prefix = ('jit_refs', 'references') if 'jit_refs' in line else ('jit_core_root', 'core-root')
                producer = name if name == 'jit_refs' else 'jit_archived_host'
                lines[i] = 'runtime_jit_products(name=' + repr(producer) + ',archive="source-products.tar.gz",sha256=' + repr(expected['sourceProductsSha256']) + ',prefix=' + repr(prefix) + ')'
                if name == 'jit_core_root':
                    lines[i] += '\nmsbuild_layout(name="jit_core_root",paths={":jit_archived_host":"."})'
                replaced += 1
        assert replaced == 2
        lines.insert(0, 'load(":runtime_jit_artifacts.bzl", "runtime_jit_products")')
        build.write_text('\n'.join(lines) + '\n')
    else:
        assert args.phase == 'consumer', 'Producer requires source-built runtime edges'
        archived = {ast.literal_eval(next(k.value for k in node.keywords if k.arg == 'name')):
                    {k.arg: ast.literal_eval(k.value) for k in node.keywords}
                    for node in ast.walk(ast.parse(original_build)) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == 'runtime_jit_products'}
        for name, prefix in [('jit_refs', 'references'), ('jit_archived_host', 'core-root')]:
            assert archived[name]['archive'] == 'source-products.tar.gz'
            assert archived[name]['sha256'] == expected['sourceProductsSha256'] and archived[name]['prefix'] == prefix
    rows = []

    def invoke(label, success=True):
        check_space()
        events = results / (label + '.bep')
        start = time.monotonic()
        with (results / (label + '.log')).open('w') as log:
            completed = subprocess.run(bazel + ['test', '//:jit_add1', *options,
                '--build_event_json_file=' + str(events)], cwd=root, stdout=log, stderr=subprocess.STDOUT)
        assert (completed.returncode == 0) == success, results / (label + '.log')
        records = [json.loads(line) for line in events.read_text().splitlines()]
        outcomes = [event['testResult'] for event in records if 'testResult' in event]
        if success or label == 'failure':
            assert len(outcomes) == 1, ('Expected one executed JIT test', label)
            outcome = outcomes[0]
            assert not outcome.get('cachedLocally') and not outcome.get('executionInfo', {}).get('cachedRemotely'), outcome
            assert outcome['status'] == ('PASSED' if success else 'FAILED'), outcome
        row = dict(case=label, seconds=time.monotonic() - start, success=success,
                   testExecuted=bool(outcomes))
        if success:
            report = json.loads((root / 'bazel-bin/jit_test_build.graph/report.json').read_text())
            row.update(hits=report['hits'], misses=report['misses'], outputs=inventory(root / 'bazel-bin/jit_test_build.graph/workspace'),
                       sourceHost=inventory(root / 'bazel-bin/jit_core_root.layout'))
            row['assemblySha256'] = digest(root / 'bazel-bin/jit_test_build.graph/workspace' / TEST_OUTPUT / 'Add1_ro.dll')
        rows.append(row)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps({k: v for k, v in row.items() if k not in ['outputs', 'sourceHost']}), flush=True)
        return row

    try:
        seed = invoke('seed' if args.phase == 'producer' else 'recovery')
        expected_counts = [(0, 3), (3, 0)] if args.reuse_producer_cache else [((0, 3) if args.phase == 'producer' else (3, 0))]
        assert (seed['hits'], seed['misses']) in expected_counts, seed
        if args.seed_report:
            expected = json.loads(args.seed_report.read_text())
            assert seed['outputs'] == expected['outputs'], 'Recovered JIT products differ'
            assert seed['sourceHost'] == expected['sourceHost'], 'Declared source runtime differs'
            metrics = next(json.loads(line)['buildMetrics']['actionSummary'] for line in
                           (results / 'recovery.bep').read_text().splitlines() if 'buildMetrics' in json.loads(line))
            assert sum(int(r.get('actionsExecuted', 0)) for r in metrics['actionData'] if r['mnemonic'] == 'MSBuildGraph') >= 1
            print('PASS: independent JIT cache recovery and fresh source-runtime execution', flush=True)
            return
        else:
            assert args.raw, 'Producer requires raw unchanged compilation'
            compiled = [path for path in seed['outputs'] if path.endswith(('.dll', '.pdb'))]
            assert len(compiled) >= 2
            for path in compiled:
                assert digest(args.raw / path) == seed['outputs'][path]['sha256'], path
            seed['comparedCompiledFiles'] = len(compiled)
            # Run the raw assembly with only source-built CORE_ROOT and system
            # libraries visible; the installed SDK is absent from this namespace.
            host = root / 'bazel-bin/jit_core_root.layout'
            command = ['bwrap', '--die-with-parent', '--unshare-user', '--unshare-pid', '--clearenv', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp']
            for path in ['/usr', '/bin', '/lib', '/lib64', '/etc/ld.so.cache']:
                if Path(path).exists():
                    command += ['--ro-bind', path, path]
            command += ['--ro-bind', str(host.resolve()), '/runtime', '--ro-bind', str((args.raw / TEST_OUTPUT).resolve()), '/test',
                        '--setenv', 'CORE_ROOT', '/runtime', '--chdir', '/test', '/runtime/corerun', '/test/Add1_ro.dll']
            with (results / 'raw-run.log').open('w') as log:
                outcome = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            assert outcome.returncode == 100, outcome.returncode
            seed['sourceProductsSha256'] = digest(products)
            shutil.copyfile(products, results / products.name)
            (results / 'seed.json').write_text(json.dumps(seed, indent=2) + '\n')
        assert original.count(b'return x+1;') == 1
        source.write_bytes(original.replace(b'return x+1;', b'return unchecked(x+1);') + ('\n// Qualification body token: ' + uuid.uuid4().hex + '\n').encode())
        body = invoke('body')
        assert (body['hits'], body['misses']) == (2, 1) and body['assemblySha256'] != seed['assemblySha256']
        source.write_bytes(original.replace(b'return x+1;', b'return x+2;'))
        invoke('failure', success=False)
        log = (results / 'failure.log').read_text()
        assert 'Expected exit code 100, received 101' in log, log[-3000:]
        source.write_bytes(original)
        restored = invoke('restored')
        assert restored['outputs'] == seed['outputs']
        generator = root / 'src/tests/Common/XUnitWrapperGenerator/XUnitWrapperGenerator.cs'
        original_generator = generator.read_bytes()
        try:
            generator.write_bytes(original_generator + b'\ninternal static class QualificationGeneratorInput {}\n')
            changed = invoke('wrapper-generator-edit')
            assert (changed['hits'], changed['misses']) == (1, 2), changed
        finally:
            generator.write_bytes(original_generator)
        restored_generator = invoke('restored-wrapper-generator')
        assert restored_generator['outputs'] == seed['outputs']
        # Omitting the reference-tree edge must fail instead of discovering host refs.
        active_build = build.read_text()
        assert active_build.count("':jit_refs': 'artifacts/bin/ref/net10.0'") == 1
        build.write_text(active_build.replace(
            ", ':jit_refs': 'artifacts/bin/ref/net10.0'", ""))
        try:
            invoke('missing-references', success=False)
        finally:
            build.write_text(active_build)
        # Remove the declared compiler archive; no host/compiler fallback allowed.
        compiler = root / '.package-source/microsoft.net.compilers.toolset.5.0.0-1.25259.6.nupkg'
        hidden = compiler.with_suffix('.missing')
        compiler.rename(hidden)
        try:
            invoke('missing-compiler', success=False)
        finally:
            hidden.rename(compiler)
        # The wrapper generator is an implementation dependency: removing a
        # declared generator source must fail, even after successful cache hits.
        hidden = generator.with_suffix('.missing')
        assert generator.is_file()
        generator.rename(hidden)
        try:
            invoke('missing-wrapper-generator', success=False)
        finally:
            hidden.rename(generator)
        assert digest(root / ENTRY) == PINNED[ENTRY] and digest(source) == PINNED[CODE]
    finally:
        source.write_bytes(original)
        build.write_text(original_build)
    print('PASS: unchanged JIT build/run, body/generator invalidation, exit semantics and missing inputs', flush=True)


if __name__ == '__main__':
    main()
