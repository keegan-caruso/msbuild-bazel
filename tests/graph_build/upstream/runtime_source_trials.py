"""Five reviewed Pipelines body edits on an isolated full-product workspace.

Requires a completed input-only closure and an independently qualified product.
The baseline and scored series are distinct. This is not an API/native rebuild
benchmark, a paired raw comparison, or a measurement of the public default cache.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import threading
import time
from urllib.parse import unquote, urlsplit
import uuid
import zipfile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_input(path, data, attributes=None):
    """Break any inherited hardlink; edited inputs get normal fresh mtimes."""
    saved = attributes or (path.stat() if path.exists() else None)
    temporary = path.with_name(path.name + '.q10-' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(data)
        os.chmod(temporary, stat.S_IMODE(saved.st_mode) if saved else 0o644)
        if attributes:
            os.utime(temporary, ns=(attributes.st_atime_ns, attributes.st_mtime_ns))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def brokers(base):
    found, processes, servers = [], {}, set()
    for process in Path('/proc').glob('[0-9]*'):
        try:
            args = process.joinpath('cmdline').read_bytes().split(b'\0')
            cwd = process.joinpath('cwd').resolve(strict=True)
            parent = next(int(line.split()[1]) for line in process.joinpath('status').read_text().splitlines() if line.startswith('PPid:'))
            pid = int(process.name)
            processes[pid] = (parent, args)
            if args and args[0].rsplit(b'/', 1)[-1] == b'java' and (cwd.is_relative_to(base) or any(str(base).encode() in arg for arg in args)):
                servers.add(pid)
        except (OSError, ValueError):
            continue
    assert servers, 'Cannot attribute the trial Bazel server'
    for pid, (parent, args) in processes.items():
        if b'worker' not in args or not any(a.endswith(b'/graph_runner.runner/GraphBuild.dll') for a in args):
            continue
        seen = set()
        while parent in processes and parent not in seen:
            if parent in servers:
                found.append(pid)
                break
            seen.add(parent)
            parent = processes[parent][0]
    return sorted(found)


def runtime_proof(records, destination):
    event = next(r for r in records if r.get('id', {}).get('testResult', {}).get('label') == '//:runtime_test')
    output = next(o for o in event['testResult']['testActionOutput'] if o['name'].endswith('outputs.zip'))
    uri = urlsplit(output['uri'])
    assert uri.scheme == 'file' and uri.netloc in ['', 'localhost']
    with zipfile.ZipFile(unquote(uri.path)) as z:
        name = next(n for n in z.namelist() if n.rsplit('/', 1)[-1] == 'runtime.json')
        proof = json.loads(z.read(name))
        logs = {n: z.read(n).decode() for n in z.namelist() if n.endswith(('.launcher.log', '.sdk-absent.log', '.package-sdk-absent.log'))}
    destination.write_text(json.dumps(proof, indent=2))
    assert proof['managed'] > 0 and proof['native'] > 0 and proof['sdkAbsentExecution'] and proof['packageVerified']
    assert len(logs) == 3
    return proof, logs


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('rules', type=Path)
    p.add_argument('workspace', type=Path)
    p.add_argument('output_base', type=Path)
    p.add_argument('results', type=Path)
    p.add_argument('--qualification-mappings', type=Path, required=True)
    p.add_argument('--expected-mappings-sha256', required=True)
    p.add_argument('--oracle', type=Path, required=True, help='strict runtime_test JSON from the successful independent product')
    p.add_argument('--revision', required=True)
    a = p.parse_args()
    rules, root, base, results = [v.resolve() for v in [a.rules, a.workspace, a.output_base, a.results]]
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert not base.exists() and not results.exists() and not results.is_relative_to(root)
    assert all(not left.is_relative_to(right) and not right.is_relative_to(left)
               for left, right in [(root, base), (root, results), (base, results)])
    assert (root / 'recovery-inputs.json').is_file(), 'Use the strict input-only closure helper'
    assert not any(root.glob('bazel-*'))
    results.mkdir(parents=True)
    sys.path.insert(0, str(rules / 'tests/graph_build/upstream'))
    sys.path.insert(0, str(rules / 'benchmarks'))
    from runtime_recovered_tests import edited_sources, graph_actions
    from resources import GuestMemory, allocated_bytes
    mutation = json.loads((rules / 'tests/graph_build/upstream/runtime_loaded_common_edit.json').read_text())
    implementation, reference = mutation['implementation'], mutation['reference']
    contract = json.loads((root / 'graph.generated.json').read_text())
    mapping = json.loads(a.qualification_mappings.read_text())
    assert digest(a.qualification_mappings) == a.expected_mappings_sha256
    assert implementation in mapping['restoreReuseInputs'], 'Never add a new qualification exemption for the trial'
    assert contract['SdkVersion'] == '11.0.100'
    variants = [(project, node) for project, value in contract['Projects'].items()
                for node in value.get('Configurations') or [value]]
    outputs = [(project, node) for project, node in variants if node['OutputDirectories'] or node.get('OutputFiles')]
    owners = [(project, node) for project, node in outputs if implementation in node['Inputs']]
    assert owners and {project for project, _ in owners} == {'src/libraries/System.IO.Pipelines/src/System.IO.Pipelines.csproj'}
    assert implementation not in contract.get('DefinitionDigests', {}) and implementation not in contract['SharedInputs']
    assert reference in {name for _, node in variants for name in node['Inputs']}
    oracle = json.loads(a.oracle.read_text())
    generated, app = root / 'graph.generated.bzl', root / 'app/Program.cs'
    files = [root / implementation, root / reference, generated, app]
    original = {str(path.relative_to(root)): path.read_bytes() for path in files}
    closure = json.loads((root / 'recovery-inputs.json').read_text())
    assert all(hashlib.sha256(original[name]).hexdigest() == closure[name]['sha256'] for name in [implementation, reference])
    attributes = {path: path.stat() for path in files}
    assert all(path.is_file() and not path.is_symlink() for path in files)
    marker = root / 'q10-baseline-marker.txt'
    assert not marker.exists()
    token = uuid.uuid4().hex
    prefix, action = original['graph.generated.bzl'].split(b'    msbuild_graph(\n')
    assert action.count(b'        srcs = [') == 1
    instrumented = prefix + b'    msbuild_graph(\n' + action.replace(b'        srcs = [', b'        srcs = ["q10-baseline-marker.txt",', 1)
    probe = b'''var q10Options = new System.IO.Pipelines.PipeOptions(pauseWriterThreshold: 1048576, resumeWriterThreshold: 524288);
if (q10Options.PauseWriterThreshold != 1048576 || q10Options.ResumeWriterThreshold != 524288) throw new InvalidOperationException("Pipelines option probe failed");
Console.WriteLine("PIPELINES_PROBE=1048576/524288");
Console.WriteLine("PIPELINES_SHA256=" + Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(System.IO.Pipelines.PipeOptions).Assembly.Location))));
'''
    assert original['app/Program.cs'].count(b'var message = ') == 1
    env = dict(os.environ, USE_BAZEL_VERSION='9.3.2', RULES_MSBUILD_PROJECT_CACHE_READ_ONLY='1',
               DOTNET_CLI_USE_MSBUILD_SERVER='false', MSBUILDUSESERVER='0')
    endpoint = env['RULES_MSBUILD_PROJECT_CACHE_URL']
    command = [str(rules / 'scripts/bazel-launcher.sh'), '--nosystem_rc', '--nohome_rc',
               '--noworkspace_rc', '--output_base=' + str(base)]
    options = ['--jobs=1', '--local_test_jobs=1', '--worker_max_instances=MSBuildGraph=1',
               '--strategy=MSBuildGraph=worker', '--worker_sandboxing', '--disk_cache=',
               '--remote_cache=' + endpoint, '--remote_cache_async=false',
               '--remote_max_connections=8', '--remote_timeout=60s',
               '--remote_upload_local_results=false', '--remote_download_outputs=all',
               '--action_env=RULES_MSBUILD_PROJECT_CACHE_URL=' + endpoint,
               '--action_env=RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=1',
               '--nocache_test_results', '--test_output=errors']
    deadline, rows, baseline, worker_ids = time.monotonic() + 3900, [], None, None
    seen_implementations = set()

    def invoke(label, limit):
        nonlocal baseline, worker_ids
        name = results / label
        stop, disk_samples = threading.Event(), []
        def disks():
            while True:
                s = os.statvfs(root)
                disk_samples.append(dict(monotonic=time.monotonic(), filesystemUsedBytes=(s.f_blocks - s.f_bfree) * s.f_frsize,
                                         availableBytes=s.f_bavail * s.f_frsize,
                                         memoryEvents=Path('/sys/fs/cgroup/memory.events').read_text()))
                if stop.wait(.5):
                    return
        sampler = threading.Thread(target=disks)
        sampler.start()
        start, memory = time.monotonic(), GuestMemory(.5)
        try:
            with memory, name.with_suffix('.log').open('w') as log:
                subprocess.run(command + ['test', '//:app_test', '//:runtime_test', '//:runtime_package',
                    *options, '--build_event_json_file=' + str(name.with_suffix('.bep')),
                    '--execution_log_json_file=' + str(name.with_suffix('.execution.json'))],
                    cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, check=True,
                    timeout=min(limit, max(1, deadline - time.monotonic())))
            seconds = time.monotonic() - start
        finally:
            stop.set()
            sampler.join()
            name.with_suffix('.disk-samples.json').write_text(json.dumps(disk_samples))
            name.with_suffix('.memory-samples.json').write_text(json.dumps(memory.samples))
        records = [json.loads(line) for line in name.with_suffix('.bep').read_text().splitlines()]
        tests = [r['testResult'] for r in records if 'testResult' in r]
        assert len(tests) == 2 and all(t['status'] == 'PASSED' and not t.get('cachedLocally')
            and not t.get('executionInfo', {}).get('cachedRemotely') for t in tests)
        actions = graph_actions(name.with_suffix('.execution.json'), ['MSBuildGraph', 'MSBuildGraphRestore', 'RuntimeNative', 'RuntimeNativeVersions', 'MSBuildSyncPrepare'])
        source = [r for r in actions if r['mnemonic'] == 'MSBuildGraph' and any('/graph.graph' in path for path in r['listedOutputs'])]
        assert len(source) == 1 and not source[0]['cacheHit'] and source[0]['runner'] == 'worker', actions
        assert not any(r['mnemonic'] == 'MSBuildSyncPrepare' for r in actions), 'No new full-source qualification in measured series'
        assert all(r['cacheHit'] for r in actions if r['mnemonic'] in ['RuntimeNative', 'RuntimeNativeVersions']), actions
        report = json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())
        assert report['hits'] + report['misses'] == len(outputs), report
        current_workers = brokers(base)
        assert current_workers
        if worker_ids is None:
            worker_ids = current_workers
        else:
            assert current_workers == worker_ids, (current_workers, worker_ids)
        proof, logs = runtime_proof(records, name.with_suffix('.runtime.json'))
        assert (proof['managed'], proof['native']) == (oracle['managed'], oracle['native'])
        tree = root / 'bazel-bin/graph.graph/workspace'
        impl_sha, ref_sha = digest(tree / mutation['implDll']), digest(tree / mutation['refDll'])
        assert impl_sha not in seen_implementations, impl_sha
        seen_implementations.add(impl_sha)
        key = next(k for k in proof['binaryHashes'] if k.endswith('/System.IO.Pipelines.dll'))
        assert proof['binaryHashes'][key] == impl_sha
        assert 'System.IO.Pipelines.dll' in proof['loadedSourceComponents']
        assert 'System.IO.Pipelines.dll' in proof['sdkAbsentLoadedSourceComponents']
        for text in logs.values():
            assert 'PIPELINES_PROBE=1048576/524288' in text
            assert 'PIPELINES_SHA256=' + impl_sha.upper() in text
        if baseline is None:
            baseline = dict(binaryHashes=proof['binaryHashes'], impl=impl_sha, ref=ref_sha)
            assert proof['binaryHashes'] == oracle['binaryHashes']
        else:
            assert len(owners) <= report['misses'] < len(outputs) and report['hits'] > 0, report
            assert impl_sha != baseline['impl'] and ref_sha == baseline['ref']
            for key, expected in baseline['binaryHashes'].items():
                if not key.endswith('.dll') or key.endswith('/System.Private.CoreLib.dll'):
                    assert proof['binaryHashes'][key] == expected, key
        rows.append(dict(case=label, seconds=seconds, hits=report['hits'], misses=report['misses'],
            configuredCompilationNodes=len(outputs), ownerVariants=len(owners), brokerPids=worker_ids,
            implementationSha256=impl_sha, referenceSha256=ref_sha, testsExecuted=2,
            memory=memory.summary(), peakWholeGuestFilesystemUsedBytes=max(r['filesystemUsedBytes'] for r in disk_samples),
            allocatedOwnedWorkspaceAndOutputBaseBytes=allocated_bytes([root, base]),
            sourceAction=source, restoreActions=[r for r in actions if r['mnemonic'] == 'MSBuildGraphRestore']))
        (results / 'summary.json').write_text(json.dumps(dict(revision=a.revision, rows=rows,
            sdkVersion=contract['SdkVersion'], bazelVersion='9.3.2',
            machine=os.uname().machine, onlineCpus=os.cpu_count(),
            policy=dict(projectCacheReadOnly=True, bazelUploads=False, jobs=1, localTestJobs=1,
                        graphWorkerInstances=1, remoteMaxConnections=8, remoteTimeoutSeconds=60,
                        baselineLimitSeconds=2400, cycleLimitSeconds=300, totalLimitSeconds=3900),
            contractSha256=digest(root / 'graph.generated.json'),
            qualificationMappingsSha256=a.expected_mappings_sha256,
            inputClosureSha256=digest(root / 'recovery-inputs.json'),
            scope='one separately reported baseline; five source body edits with native/CoreLib unchanged; instrumented private fixture, no API/native rebuild or raw speedup claim'), indent=2))
        print(json.dumps({k: rows[-1][k] for k in ['case', 'seconds', 'hits', 'misses', 'implementationSha256']}), flush=True)

    try:
        replace_input(marker, token.encode())
        replace_input(generated, instrumented)
        replace_input(app, original['app/Program.cs'].replace(b'var message = ', probe + b'var message = ', 1))
        invoke('baseline', 2400)
        originals = {implementation: original[implementation], reference: original[reference]}
        for cycle in range(5):
            changes = edited_sources(originals, mutation, 'body', token + '-' + str(cycle))
            assert set(changes) == {implementation}
            replace_input(root / implementation, changes[implementation])
            assert digest(root / implementation) != hashlib.sha256(original[implementation]).hexdigest()
            invoke('body-' + str(cycle), 300)
        print('PASS: five bounded source Pipelines body edits, real constructor/product tests, stable workers and unchanged native/CoreLib')
    finally:
        for path, saved in attributes.items():
            replace_input(path, original[str(path.relative_to(root))], saved)
        marker.unlink(missing_ok=True)
        subprocess.run(command + ['shutdown'], cwd=root, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)


if __name__ == '__main__':
    main()
