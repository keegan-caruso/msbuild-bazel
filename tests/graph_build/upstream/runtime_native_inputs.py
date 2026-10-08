"""Bounded source/header/compiler edits in the declared upstream runtime host.

Each native edit must execute only the host producer, refresh its composed files,
rerun real suites and expose current producer hashes. This does not claim raw
native compiler parity or qualification of other native components/platforms.
"""
import argparse
from collections import Counter
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import uuid
import xml.etree.ElementTree as ET

from runtime_suite_verify import proofs

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests/runtime'))
from case_names import normalize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['workspace', 'results']:
        parser.add_argument(name, type=Path)
    parser.add_argument('--case', choices=['source', 'header', 'tool'], help='run one independent mutation and restoration')
    parser.add_argument('--action-cache', type=Path, help='reuse a qualification-owned native action cache')
    parser.add_argument('--output-base', type=Path, required=True)
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    root, results = args.workspace.resolve(), args.results.resolve()
    assert not results.is_relative_to(root)
    results.mkdir(parents=True, exist_ok=False)
    application = json.loads((root / 'application.json').read_text())
    suite = json.loads((root / 'suite.json').read_text())
    assert len(suite['tests']) == 8 and application['native']['libhostfxr.so']['producer'] == 'host'
    environment = dict(os.environ, USE_BAZEL_VERSION='9.3.0')
    for name in ['RULES_MSBUILD_PROJECT_CACHE_URL', 'RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', 'RULES_MSBUILD_GRAPH_PROFILE']:
        environment.pop(name, None)
    bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(args.output_base.resolve())]
    options = ['--jobs=1', '--local_test_jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing',
               '--worker_max_instances=MSBuildGraph=1', '--disk_cache=' + str((args.action_cache or results / 'action-cache').resolve()), '--remote_cache=',
               '--test_output=errors', '--remote_download_outputs=all', '--noshow_progress']
    native_targets = sorted({'//' + p['producer'] + ':runtime' for p in application['native'].values()})
    # Disk-cache dependency outputs may remain on demand after downstream cache
    # hits. Materialize producers and composed layouts before inspecting bytes.
    with (results / 'materialize-native.log').open('w') as log:
        subprocess.run(bazel + ['build', *native_targets, *[o for o in options if not o.startswith(('--local_test_jobs', '--test_output'))]],
                       cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
    def capture():
        return {name: hashlib.sha256((root / 'bazel-bin' / p['producer'] / 'runtime.generated' / name).read_bytes()).hexdigest().upper()
                for name, p in application['native'].items()}
    def cases():
        return {test['target']: normalize(Counter((c.get('name'), 'Failed' if c.find('failure') is not None or c.find('error') is not None
            else 'NotExecuted' if c.find('skipped') is not None else 'Passed') for c in
            ET.parse(root / 'bazel-testlogs' / test['target'].removeprefix('//:') / 'test.xml').getroot().findall('.//testcase')))
            for test in suite['tests']}
    original_cases, original_products = cases(), capture()
    assert sum(sum(c.values()) for c in original_cases.values()) == 119016
    archives = [root / 'host/source.tar', root / 'host/toolchain.tar']
    backups = [p.with_suffix('.qualification-save') for p in archives]
    assert not any(p.exists() for p in backups)
    rows = []
    run_token = uuid.uuid4().hex
    def test(label, changed, token=None):
        event = results / (label + '.bep')
        with (results / (label + '.log')).open('w') as log:
            subprocess.run(bazel + ['test', '//:runtime_suites', *native_targets, *options, '--build_event_json_file=' + str(event)],
                           cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        events = [json.loads(line) for line in event.read_text().splitlines()]
        metrics = next(e['buildMetrics']['actionSummary'] for e in events if 'buildMetrics' in e)
        actions = {r['mnemonic']: int(r.get('actionsExecuted', 0)) for r in metrics.get('actionData', [])}
        graph_actions = actions.get('MSBuildGraph', 0)
        if label == 'baseline':
            # Restoring the authored declarations after an import control may
            # execute a graph action once. It must replay every original node.
            # Setup also includes seven auxiliary generation graphs.
            if graph_actions:
                report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
                assert (report['hits'], report['misses']) == (481, 0), report
        else:
            assert graph_actions == actions.get('MSBuildGraphRestore', 0) == 0, actions
        if changed:
            assert actions.get('RuntimeNative') == 1, actions
        assert cases() == original_cases, label
        products = capture()
        assert all(products[n] == original_products[n] for n, p in application['native'].items() if p['producer'] != 'host')
        if changed:
            assert products['libhostfxr.so'] != original_products['libhostfxr.so']
            assert token.encode() in (root / 'bazel-bin/host/runtime.generated/libhostfxr.so').read_bytes()
        else:
            assert products == original_products, 'Exact native restoration'
        host = root / 'bazel-bin' / suite['host']
        for name, producer in application['native'].items():
            assert hashlib.sha256((host / producer['path']).read_bytes()).hexdigest().upper() == products[name]
        tests = [e['testResult'] for e in events if 'testResult' in e]
        assert len(tests) == 8 and all(t['status'] == 'PASSED' for t in tests)
        if changed:
            assert all(not t.get('cachedLocally') for t in tests)
        observations = 0
        for selection in suite['tests']:
            label_name = selection['target'].removeprefix('//:')
            observed = proofs(root / 'bazel-testlogs' / label_name / 'test.outputs')
            assert observed
            for proof in observed:
                for name in ['dotnet', 'libhostfxr.so', 'libhostpolicy.so']:
                    if name in proof['files']:
                        assert proof['files'][name]['sha256'] == products[name], (label_name, name)
                        observations += 1
        assert observations > 0
        row = dict(case=label, nativeActions=actions.get('RuntimeNative', 0), graphActions=graph_actions,
                   testOutcomes=119016, nativeProducts=products, nativeHashObservations=observations,
                   testsCached=sum(bool(t.get('cachedLocally')) for t in tests))
        rows.append(row)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps(row), flush=True)
    def rewrite(original, destination, replacements, additions=None):
        with tarfile.open(original) as source, tarfile.open(destination, 'w') as target:
            seen = set()
            for member in source:
                assert member.name not in seen
                seen.add(member.name)
                if member.name in replacements:
                    body = replacements[member.name]
                    replacement = tarfile.TarInfo(member.name)
                    replacement.mode = member.mode
                    replacement.size = len(body)
                    target.addfile(replacement, io.BytesIO(body))
                else:
                    target.addfile(member, source.extractfile(member) if member.isfile() else None)
            assert replacements.keys() <= seen
            for name, body, mode in additions or []:
                assert name not in seen
                member = tarfile.TarInfo(name); member.mode = mode; member.size = len(body)
                target.addfile(member, io.BytesIO(body))
    try:
        test('baseline', False)
        for kind in ['source', 'header', 'tool']:
            if args.case and args.case != kind:
                continue
            index = int(kind == 'tool')
            archive, backup = archives[index], backups[index]
            archive.rename(backup)
            token = 'qualification-native-' + kind + '-' + run_token
            try:
                if kind == 'source':
                    name = 'artifacts/obj/_version.c'
                    with tarfile.open(backup) as source:
                        body = source.extractfile(name).read()
                    assert body.count(b'@Commit:') == 1
                    rewrite(backup, archive, {name: body.replace(b'@Commit:', token.encode() + b' @Commit:')})
                elif kind == 'header':
                    name = 'src/native/corehost/hostfxr.h'
                    with tarfile.open(backup) as source:
                        body = source.extractfile(name).read()
                    guard = b'#endif // HAVE_HOSTFXR_H'
                    assert body.count(guard) == 1
                    marker = b'static const char QualificationHeaderProbe[] __attribute__((used, retain)) = "' + token.encode() + b'";\n'
                    body = body.replace(guard, marker + guard)
                    rewrite(backup, archive, {name: body})
                else:
                    name = 'usr/lib/llvm-14/bin/clang'
                    with tarfile.open(backup) as source:
                        compiler = source.extractfile(name).read()
                    wrapper = b'#!/bin/sh\nmode=\ncase "$0" in *clang++*) mode=--driver-mode=g++ ;; esac\nexec /usr/lib/llvm-14/bin/clang.qualification-real $mode -include /qualification-native-tool.h "$@"\n'
                    marker = b'static const char QualificationToolProbe[] __attribute__((used, retain)) = "' + token.encode() + b'";\n'
                    rewrite(backup, archive, {name: wrapper}, [('usr/lib/llvm-14/bin/clang.qualification-real', compiler, 0o755),
                                                               ('qualification-native-tool.h', marker, 0o644)])
                test(kind + '-edit', True, token)
            finally:
                archive.unlink(missing_ok=True)
                backup.rename(archive)
            test(kind + '-restored', False)
        print('PASS: native source/header/tool edits, bounded invalidation, host/test consumption and exact restoration', flush=True)
    finally:
        for archive, backup in zip(archives, backups):
            if backup.exists():
                archive.unlink(missing_ok=True); backup.rename(archive)


if __name__ == '__main__':
    main()
