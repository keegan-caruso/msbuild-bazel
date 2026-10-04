"""Qualify normal Bazel Restore recovery and independent project-cache recovery.

Use declared runtime inputs, a new output base, and an independent relocated
consumer container. Stop the producer before running the consumer.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]


def spawns(path):
    text, decoder, result = path.read_text(), json.JSONDecoder(), []
    while text.strip():
        row, end = decoder.raw_decode(text.lstrip())
        text = text.lstrip()[end:]
        result.append(row)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--cache-url', required=True)
    parser.add_argument('--phase', choices=['producer', 'consumer'], required=True)
    parser.add_argument('--seed-evidence', type=Path)
    parser.add_argument('--diagnostics', action='store_true')
    parser.add_argument('--edits', action='store_true', help='consumer-only body/API and recovery controls using the retained worker')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert (args.phase == 'consumer') == (args.seed_evidence is not None)
    assert not args.edits or args.phase == 'consumer'
    root, results, base = args.workspace.resolve(), args.results.resolve(), args.output_base.resolve()
    assert not base.exists() and not results.exists()
    assert not results.is_relative_to(root) and not root.is_relative_to(results)
    assert not base.is_relative_to(root) and not root.is_relative_to(base)
    results.mkdir(parents=True)
    contract = json.loads((root / 'graph.generated.json').read_text())
    assert contract.get('Restore'), 'This qualification must include prepared Restore'
    nodes = [(path, node) for path, declaration in contract['Projects'].items()
             for node in declaration.get('Configurations') or [declaration]]
    count = sum(bool(node['OutputDirectories'] or node.get('OutputFiles')) for _, node in nodes)
    directories = {path for _, node in nodes for path in node['OutputDirectories']}
    outputs = {path for _, node in nodes for path in node.get('OutputFiles', [])}
    disposable = {directory + '/' + Path(project).name + '.GenerateResource.cache'
                  for project, node in nodes for directory in node['OutputDirectories'] if directory.startswith('artifacts/obj/')}
    seed = json.loads(args.seed_evidence.read_text()) if args.seed_evidence else None
    if seed:
        assert seed['machine'] != socket.gethostname() and seed['workspace'] != str(root), 'Require an independent relocated consumer'
        assert seed['contractSha256'] == hashlib.sha256((root / 'graph.generated.json').read_bytes()).hexdigest()
    mutation = json.loads(Path(__file__).with_name('runtime_source_host_edit.json').read_text()) if args.edits else None
    originals = {path: (root / path).read_bytes() for path in [mutation['implementation'], mutation['reference']]} if mutation else {}
    if mutation:
        assert count == mutation['compiled'] and contract['Entries'] == mutation['entries']
    environment = dict(os.environ, USE_BAZEL_VERSION='9.2.0')
    environment.pop('RULES_MSBUILD_GRAPH_PROFILE', None)
    environment.pop('RULES_MSBUILD_PROJECT_CACHE_URL', None)
    environment.pop('RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN', None)
    bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(base)]
    options = ['--jobs=1', '--strategy=MSBuildGraph=worker', '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1',
               '--spawn_strategy=linux-sandbox', '--disk_cache=', '--remote_cache=' + args.cache_url,
               '--remote_cache_async=false', '--remote_download_outputs=all', '--noshow_progress',
               '--remote_upload_local_results=' + str(args.phase == 'producer').lower(),
               '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + args.cache_url]
    if environment.get('RULES_MSBUILD_TEST_REPOSITORY_CACHE'):
        options.append('--repository_cache=' + environment['RULES_MSBUILD_TEST_REPOSITORY_CACHE'])
    generated = root / 'graph.generated.bzl'
    original = generated.read_text()
    prefix, action = original.split('    msbuild_graph(\n', 1)
    assert '"complete-cache-request.txt"' not in original
    action = action.replace('        srcs = [', '        srcs = ["complete-cache-request.txt",', 1)
    generated.write_text(prefix + '    msbuild_graph(\n' + action)
    nonce = root / 'complete-cache-request.txt'
    assert not nonce.exists()
    nonce.write_text('complete-cache-seed')
    rows = []

    def invoke(arguments, label):
        start = time.monotonic()
        with (results / (label + '.log')).open('w') as log:
            subprocess.run(bazel + arguments, cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True)
        return time.monotonic() - start

    def capture():
        artifact = root / 'bazel-bin/graph.graph'
        workspace = artifact / 'workspace'
        paths = {workspace / path for path in outputs} | {path for directory in directories for path in (workspace / directory).rglob('*')}
        files = {str(path.relative_to(workspace)): dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), mode=path.stat().st_mode & 0o777)
                 for path in paths if path.is_file() and not path.name.endswith('.AssemblyReference.cache')
                 and (str(path.relative_to(workspace)) not in disposable or str(path.relative_to(workspace)) in outputs)}
        return json.loads((artifact / 'report.json').read_text()), files

    def build(label, whole=False, profile=False, incremental=False, edit=None):
        log = results / (label + '.execution.json')
        seconds = invoke(['build', '//:graph', *options, '--execution_log_json_file=' + str(log)], label)
        actions = spawns(log)
        restore = [row for row in actions if row.get('mnemonic') == 'MSBuildGraphRestore']
        graph = [row for row in actions if row.get('mnemonic') == 'MSBuildGraph']
        assert len(graph) == 1 and (len(restore) <= 1 if incremental else len(restore) == 1), (len(restore), len(graph))
        report, files = capture()
        assert report['preparedRestore'] and report['readOnlyPreparedPackages']
        if args.phase == 'consumer':
            if edit:
                assert len(files) == len(seed['files'])
                assert files[mutation['implDll']] != seed['files'][mutation['implDll']]
                assert (files[mutation['refDll']] == seed['files'][mutation['refDll']]) == (edit == 'body')
            else:
                assert files == seed['files'], 'Independent product bytes/modes differ'
            assert all(row.get('cacheHit') and row['runner'] == 'remote cache hit' for row in restore), restore
            assert bool(graph[0].get('cacheHit')) == whole, graph
            if whole:
                assert graph[0]['runner'] == 'remote cache hit'
                assert report == seed['report'], 'Whole-action report must be identified as producer metadata'
            else:
                misses = mutation['expectedMisses'][edit] if edit else 0
                assert (report['hits'], report['misses']) == (count - misses, misses), report
        else:
            assert not restore[0].get('cacheHit') and not graph[0].get('cacheHit')
            assert (report['hits'], report['misses']) == (0, count), report
        phases = {row['mnemonic']: dict(cacheHit=row.get('cacheHit', False), runner=row['runner'],
                  seconds=float(row['metrics']['totalTime'].removesuffix('s')) if row.get('metrics', {}).get('totalTime') else None,
                  metrics=row.get('metrics', {}))
                  for row in restore + graph}
        record = dict(case=label, seconds=seconds, profiled=profile, machine=socket.gethostname(), workspace=str(root),
                      configuredNodes=len(nodes), compilationNodes=count, files=files, report=report, phases=phases,
                      contractSha256=hashlib.sha256((root / 'graph.generated.json').read_bytes()).hexdigest(),
                      reportIsCached=whole, scope='Restore plus graph recovery; acquisition separately reported; no runtime suite/RBE claim')
        (results / (label + '.json')).write_text(json.dumps(record, indent=2) + '\n')
        rows.append({key: value for key, value in record.items() if key not in ['files', 'report']})
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        print(json.dumps(rows[-1]), flush=True)

    def fresh_base(label):
        # These bases were absent at entry and created only by this qualification.
        # Keep hash records/logs, not multi-gigabyte local action results between
        # independent rows. This also prevents a previous row satisfying recovery.
        invoke(['clean', '--expunge'], label + '-clean')
        new_base = base.with_name(base.name + '-' + label)
        assert not new_base.exists()
        bazel[1] = '--output_base=' + str(new_base)
        bootstrap(label)

    def bootstrap(label):
        seconds = invoke(['build', '//:packages', '//:graph_runner', *options], label + '-bootstrap')
        (results / (label + '-acquisition.json')).write_text(json.dumps(dict(seconds=seconds,
            scope='declared SDK/package acquisition and runner bootstrap; excludes Restore and graph execution')) + '\n')

    try:
        # Downloads/bootstrap are separate; this must not execute Restore or Build.
        bootstrap('initial')
        if args.phase == 'producer':
            build('seed')
        else:
            build('whole-action-recovery', whole=True)
            fresh_base('project-recovery')
            nonce.write_text('force-project-recovery')
            build('project-recovery')
            if mutation:
                path, anchor = mutation['implementation'], mutation['bodyAnchor'].encode()
                assert originals[path].count(anchor) == 1
                (root / path).write_bytes(originals[path].replace(anchor,
                    anchor + b'\n            GC.KeepAlive("full-child-verification");'))
                build('body', incremental=True, edit='body')
                declaration = b'\n        /// <summary>Qualification edit control.</summary>\n        public const int VerificationProbe = 7341;'
                for path, anchor in [(mutation['implementation'], mutation['implementationAnchor'].encode()),
                                     (mutation['reference'], mutation['referenceAnchor'].encode())]:
                    assert originals[path].count(anchor) == 1
                    (root / path).write_bytes(originals[path].replace(anchor, anchor + declaration))
                build('api', incremental=True, edit='api')
                for path, content in originals.items():
                    (root / path).write_bytes(content)
                nonce.write_text('post-edit-recovery')
                build('post-edit-recovery', incremental=True)
            if args.diagnostics:
                fresh_base('diagnostic')
                # Profile compilation only; profiling Restore would alter its action key.
                assert action.count('        profile_build = profile_build,') == 1
                generated.write_text(prefix + '    msbuild_graph(\n' + action.replace('        profile_build = profile_build,', '        profile_build = True,'))
                nonce.write_text('diagnostic-project-recovery')
                build('project-recovery-diagnostic', profile=True)
        print('PASS: independent complete-cache ' + args.phase, flush=True)
    finally:
        for path, content in originals.items():
            (root / path).write_bytes(content)
        generated.write_text(original)
        nonce.unlink(missing_ok=True)
        subprocess.run(bazel + ['shutdown'], cwd=root, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
