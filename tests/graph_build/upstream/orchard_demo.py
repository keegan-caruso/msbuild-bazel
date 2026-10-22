"""Measure fresh-output Orchard CI builds and HTTP recovery; keep reports outside Git."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import time
import urllib.request
import uuid

from orchard_demo_prepare import ENTRY, ROOT, digest
from orchard_http_smoke import check


def actions(path):
    text, decoder = path.read_text(), json.JSONDecoder()
    while text.strip():
        row, end = decoder.raw_decode(text.lstrip())
        yield row
        text = text.lstrip()[end:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path)
    parser.add_argument('results', type=Path)
    parser.add_argument('--output-base', type=Path, required=True)
    parser.add_argument('--cache-url', required=True)
    parser.add_argument('--phase', choices=['seed', 'recover', 'edits'], required=True)
    parser.add_argument('--seed', type=Path)
    parser.add_argument('--sdk', type=Path, help='same pinned SDK for raw Restore+Build controls')
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--sample-start', type=int, default=0, help='continue alternating order in a fresh results directory')
    parser.add_argument('--only', choices=['body', 'api'], help='restrict edit samples to one reviewed scenario')
    parser.add_argument('--edits', type=Path, default=Path(__file__).with_name('orchard_edits.json'))
    parser.add_argument('--reference-assembly', default='src/OrchardCore/OrchardCore.Abstractions/obj/Release/net10.0/ref/OrchardCore.Abstractions.dll')
    parser.add_argument('--trim-between-rows', action='store_true', help='return freed blocks on a disposable root-owned Linux filesystem, outside timing')
    parser.add_argument('--discard-output-bases', action='store_true', help='remove each owned Bazel output base after saving evidence and running the smoke test')
    parser.add_argument('--host-space-path', type=Path, help='host bind mount used to abort before physical storage is exhausted')
    parser.add_argument('--download-outputs', choices=['all', 'toplevel'], default='all', help='all verifies the full graph; toplevel verifies the app layout needed by CI')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert args.samples > 0 and args.sample_start >= 0
    root, results, base = args.workspace.resolve(), args.results.resolve(), args.output_base.resolve()
    assert not results.exists() and not base.exists()
    assert not results.is_relative_to(root) and not base.is_relative_to(root)
    assert not results.is_relative_to(base) and not base.is_relative_to(results)
    assert not Path(args.reference_assembly).is_absolute() and '..' not in Path(args.reference_assembly).parts
    assert args.phase == 'seed' or args.seed is not None
    results.mkdir(parents=True)
    contract = json.loads((root / 'graph.generated.json').read_text())
    variants = [v for p in contract['Projects'].values() for v in p.get('Configurations') or [p]]
    assert len(contract['Projects']) == sum(bool(v['OutputDirectories'] or v.get('OutputFiles')) for v in variants) == 202
    directories = {p for v in variants for p in v['OutputDirectories']}
    files = {p for v in variants for p in v.get('OutputFiles', [])}
    seed = json.loads(args.seed.read_text()) if args.seed else None
    if seed:
        assert seed['contractSha256'] == digest(root / 'graph.generated.json')
    bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--batch', '--nosystem_rc', '--nohome_rc', '--noworkspace_rc',
             '--output_base=' + str(base)]
    options = ['--jobs=4', '--strategy=MSBuildGraph=worker', '--worker_sandboxing', '--worker_max_instances=MSBuildGraph=1',
               '--spawn_strategy=linux-sandbox', '--disk_cache=', '--remote_cache=' + args.cache_url,
               '--remote_cache_async=false', '--remote_download_outputs=' + args.download_outputs, '--noshow_progress',
               '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + args.cache_url]
    if args.phase == 'recover':
        options.append('--lockfile_mode=error')
    if os.environ.get('RULES_MSBUILD_TEST_REPOSITORY_CACHE'):
        options.append('--repository_cache=' + os.environ['RULES_MSBUILD_TEST_REPOSITORY_CACHE'])
    token = os.environ.get('RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN')
    if token:
        options.append('--action_env=RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN')
    if args.phase != 'recover':
        # Catch a read-only/unhealthy service before an expensive unscored seed.
        data = ('orchard-demo-health-' + uuid.uuid4().hex).encode()
        url = args.cache_url.rstrip('/') + '/cas/' + hashlib.sha256(data).hexdigest()
        headers = {'Authorization': 'Bearer ' + token} if token else {}
        urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method='PUT'), timeout=10).close()
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=10) as response:
            assert response.read() == data
    rows = []
    smoke_rows = []
    worker_parent = Path('/tmp') / ('rules-msbuild-workers-' + str(os.geteuid()))

    def leases():
        if not worker_parent.exists():
            return set()
        assert not worker_parent.is_symlink() and worker_parent.stat().st_uid == os.geteuid()
        assert worker_parent.stat().st_mode & 0o777 == 0o700
        return set(worker_parent.glob('*.lease'))

    def reap(paths):
        # Batch Bazel can terminate workers without running their finally blocks.
        # Match production's lease check, only for workers this command created.
        removed = False
        for path in paths:
            if not re.fullmatch('[a-f0-9]{32}', path.stem):
                continue
            try:
                with os.fdopen(os.open(path, os.O_RDWR | os.O_NOFOLLOW), 'r+b') as lease:
                    try:
                        fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        continue
                    directory = path.with_suffix('')
                    assert not directory.is_symlink()
                    if directory.exists():
                        shutil.rmtree(directory)
                    path.unlink()
                    removed = True
            except FileNotFoundError:
                pass
        return removed

    def trim():
        if args.trim_between_rows:
            subprocess.run(['fstrim', '/'], check=True, stdout=subprocess.DEVNULL)

    def execute(command, label, cwd=root):
        before = leases()
        start = time.monotonic()
        with (results / (label + '.log')).open('w') as log:
            with subprocess.Popen(list(map(str, command)), cwd=cwd, stdout=log, stderr=subprocess.STDOUT) as process:
                while process.poll() is None:
                    if args.host_space_path:
                        disk = os.statvfs(args.host_space_path)
                        if disk.f_bavail * disk.f_frsize < 2 * 1024**3:
                            process.send_signal(signal.SIGINT)
                            process.wait(timeout=60)
                            raise RuntimeError('Aborted run before exhausting host disk space; exclude this sample')
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        pass
                if process.returncode:
                    raise subprocess.CalledProcessError(process.returncode, command)
        seconds = time.monotonic() - start
        if args.discard_output_bases and reap(leases() - before):
            trim()
        return seconds

    def inventory(workspace):
        paths = {workspace / p for p in files} | {p for d in directories for p in (workspace / d).rglob('*')}
        return {str(p.relative_to(workspace)): dict(sha256=digest(p), mode=p.stat().st_mode & 0o777)
                for p in sorted(paths) if p.is_file() and not p.name.endswith('.AssemblyReference.cache')}

    def reference(workspace):
        return digest(workspace / args.reference_assembly)

    def build(label, selected_base=base, whole=False):
        command = bazel[:-1] + ['--output_base=' + str(selected_base)]
        trace = results / (label + '.actions.json')
        seconds = execute(command + ['build', '//:app', *options, '--execution_log_json_file=' + str(trace)], label)
        spawns = list(actions(trace))
        graphs = [a for a in spawns if a.get('mnemonic') == 'MSBuildGraph']
        restores = [a for a in spawns if a.get('mnemonic') == 'MSBuildGraphRestore']
        assert len(graphs) == 1 and (len(restores) <= 1 if args.phase == 'seed' else len(restores) == 1)
        if whole:
            assert all(a.get('cacheHit') and a.get('runner') == 'remote cache hit' for a in graphs + restores)
        artifact = root / 'bazel-bin/graph.graph'
        if whole and args.download_outputs == 'toplevel':
            application = root / 'bazel-bin/app.runtime'
            outputs = {str(p.relative_to(application)): dict(sha256=digest(p), mode=p.stat().st_mode & 0o777)
                       for p in sorted(application.rglob('*')) if p.is_file()}
            report = {}
            ref = None  # Reference assemblies are not downloaded in this mode.
        else:
            report = json.loads((artifact / 'report.json').read_text())
            outputs = inventory(artifact / 'workspace')
            ref = reference(artifact / 'workspace')
            (results / (label + '-runner.json')).write_text(json.dumps(report, indent=2) + '\n')
        row = dict(case=label, engine='bazel', seconds=seconds, wholeActionHit=whole,
                   hits=None if whole else report['hits'], misses=None if whole else report['misses'],
                   restoreRemoteHit=bool(restores and restores[0].get('cacheHit')), files=len(outputs),
                   reference=ref, downloadOutputs=args.download_outputs,
                   remoteSpawnHits=sum(a.get('runner') == 'remote cache hit' for a in spawns),
                   executedMnemonics=[a['mnemonic'] for a in spawns if not a.get('cacheHit')])
        rows.append(row)
        print(json.dumps(row), flush=True)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        return outputs, row

    def raw(label):
        assert args.sdk and (args.sdk / 'sdk/10.0.400/MSBuild.dll').is_file()
        workspace = results / (label + '-source')
        shutil.copytree(root, workspace, ignore=shutil.ignore_patterns('bazel-*', 'bin', 'obj', '.nuget'))
        scratch = results / (label + '-scratch'); scratch.mkdir()
        command = ['bash', ROOT / 'tests/graph_build/upstream/runtime_raw.sh', args.sdk, workspace, scratch,
                   'msbuild', ENTRY, '-m:4', '-nologo', '-clp:PerformanceSummary',
                   '-p:UseSharedCompilation=false',
                   '-p:NuGetAudit=false', '-p:RestoreSources=/__rules_msbuild_graph/output/workspace/.package-source',
                   '-p:PathMap=/__rules_msbuild_graph/output/workspace=/_/workspace%2C/__rules_msbuild_graph/sdk=/_/sdk']
        properties = ['-p:' + key + '=' + value for key, value in contract['Properties'].items() if key != 'TargetFramework']
        # Restore the generator's authored netstandard framework as well as net10.
        # This is the same two-phase boundary as the prepared graph action.
        start = time.monotonic()
        execute(command + properties + ['-t:Restore'], label + '-restore')
        execute(command + properties + ['-t:Build', '-graphBuild', '-p:TargetFramework=net10.0'], label + '-build')
        seconds = time.monotonic() - start
        outputs = inventory(workspace)
        csc = re.findall(r'\bCsc\s+(\d+)\s+calls', (results / (label + '-build.log')).read_text())
        assert csc == ['202'], csc
        row = dict(case=label, engine='raw', seconds=seconds, files=len(outputs), reference=reference(workspace), cscCalls=202)
        rows.append(row)
        print(json.dumps(row), flush=True)
        (results / 'summary.json').write_text(json.dumps(rows, indent=2) + '\n')
        application = workspace / 'src/OrchardCore.Cms.Web/bin/Release/net10.0/OrchardCore.Cms.Web.dll'
        check([args.sdk / 'dotnet', application], results / (label + '-http.log'), cwd=application.parent)
        # Keep hash inventories, not another full copy of all 202 output trees.
        (results / (label + '-outputs.json')).write_text(json.dumps(outputs) + '\n')
        shutil.rmtree(workspace)
        trim()
        return outputs, row

    def smoke(label, selected_base=base):
        command = bazel[:-1] + ['--output_base=' + str(selected_base)]
        seconds = execute(command + ['test', '//:smoke', *options, '--nocache_test_results', '--test_output=all'], label + '-tests')
        print(json.dumps(dict(case=label, smoke='actual Bazel HTTP test', testCommandSeconds=seconds)), flush=True)
        smoke_rows.append(dict(case=label, seconds=seconds))
        (results / 'smoke.json').write_text(json.dumps(smoke_rows, indent=2) + '\n')

    def discard(selected_base):
        if args.discard_output_bases:
            shutil.rmtree(selected_base)
            trim()

    if args.phase == 'seed':
        if args.sdk:
            raw('raw-clean')
        # Seed is setup, not a cold-build score. Release Restore scratch blocks
        # before compiling the graph, keeping peak physical storage bounded.
        restore_seconds = execute(bazel + ['build', '//:graph_restore', *options], 'seed-restore')
        print(json.dumps(dict(case='seed-restore', seconds=restore_seconds, scored=False)), flush=True)
        trim()
        outputs, row = build('seed')
        assert row['misses'] == 202 and row['hits'] == 0, row
        value = dict(machine=socket.gethostname(), workspace=str(root), contractSha256=digest(root / 'graph.generated.json'),
                     outputs=outputs, reference=row['reference'], rows=rows)
        (results / 'seed.json').write_text(json.dumps(value) + '\n')
        smoke('seed')
        discard(base)
    elif args.phase == 'recover':
        outputs, _ = build('recover', whole=True)
        expected = seed['outputs']
        if args.download_outputs == 'toplevel':
            prefix = 'src/OrchardCore.Cms.Web/bin/Release/net10.0/'
            expected = {path[len(prefix):]: value for path, value in expected.items() if path.startswith(prefix)}
        assert outputs == expected, 'Remote recovery changed output bytes or modes'
        smoke('recover')
        print(json.dumps(dict(independentMachine=seed['machine'] != socket.gethostname(), relocated=seed['workspace'] != str(root))), flush=True)
        discard(base)
    else:
        edit = [item for item in json.loads(args.edits.read_text()) if item['name'] in ('body', 'api')]
        if args.only:
            edit = [item for item in edit if item['name'] == args.only]
        originals = {item['path']: (root / item['path']).read_bytes() for item in edit}
        assert edit
        baseline_reference = seed['outputs'][args.reference_assembly]['sha256']
        try:
            for sample in range(args.sample_start, args.sample_start + args.samples):
                for item in edit:
                    for path, data in originals.items():
                        (root / path).write_bytes(data)
                    path = root / item['path']
                    before = originals[item['path']].decode()
                    assert before.count(item['before']) == 1
                    after = item['sampleAfter'].replace('${sample}', uuid.uuid4().hex)
                    path.write_text(before.replace(item['before'], after))
                    label = item['name'] + '-' + str(sample)
                    (results / (label + '-edit.json')).write_text(json.dumps(dict(path=item['path'], before=item['before'], after=after, sourceSha256=digest(path))) + '\n')
                    raw_output = None
                    if args.sdk and sample % 2 == 0:
                        raw_output, _ = raw(label + '-raw')
                    output, row = build(label, base / label)
                    assert row['reference'] == baseline_reference if item['name'] == 'body' else row['reference'] != baseline_reference
                    if item['name'] == 'body':
                        assert (row['hits'], row['misses']) == (201, 1), row
                    smoke(label, base / label)
                    discard(base / label)
                    if args.sdk and sample % 2 != 0:
                        raw_output, _ = raw(label + '-raw')
                    if raw_output is not None:
                        required = {p for p in output if Path(p).suffix in ('.dll', '.pdb', '.resources')}
                        raw_required = {p for p in raw_output if Path(p).suffix in ('.dll', '.pdb', '.resources')}
                        assert required == raw_required, 'Raw/Bazel product sets differ'
                        different = [p for p in sorted(required) if raw_output[p]['sha256'] != output[p]['sha256']]
                        (results / (label + '-parity.json')).write_text(json.dumps(dict(files=len(required), changed=different)) + '\n')
                        print(json.dumps(dict(case=label, comparedFiles=len(required), differentFiles=len(different))), flush=True)
        finally:
            for path, data in originals.items():
                (root / path).write_bytes(data)


if __name__ == '__main__':
    main()
