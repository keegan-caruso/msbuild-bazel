"""Fresh-consumer builds from an immutable HTTP project-cache snapshot.

Same macOS ARM64 host and SDK; isolated source/Bazel/preparation/build states.
Loopback HTTP with optional per-request delay, not independent machines or WAN.
All native preparation, download, validation, staging, build and upload are timed.
SDK/package acquisition and Restore, application/hash oracles and shutdown are
excluded on both paths. Raw builds start without compiler outputs for each case.
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from native_workflow import Workflow, BAZEL, DOTNET_ROOT, remove_tree
from portable_cache import environment
from probe_native_serilog import hashes
from probe_http_cache import CacheServer
from protected_store import ProtectedStore
from synthetic_graph import generate, name, oracle


def measure(output, count=100, repetitions=3, delay_ms=10):
    output.mkdir(parents=True, exist_ok=False)
    report = dict(accepted=False, scope=__doc__, count=count, repetitions=repetitions, delayMs=delay_ms,
        profile='fresh controller with explicit protected Nix store; remote preparation with fresh Bazel state',
        changedCases={'unchanged': None, 'leaf': count - 2, 'shared': 0, 'empty': None}, samples=[],
        transport='native project bundles and portable preparation in HTTP CAS; explicit catalog digest, not Bazel ActionResult or remote execution')
    (output / 'protocol.json').write_text(json.dumps(report, indent=2))
    def save(): (output / 'report.json').write_text(json.dumps(report, indent=2))
    states = []
    reference_oracle = None
    def run(command, root, log):
        result = subprocess.run(list(map(str, command)), cwd=root,
            env=dict(environment(DOTNET_ROOT, output / 'home', output, root), MSBuildEnableWorkloadResolver='false'),
            capture_output=True, text=True, timeout=900)
        text = result.stdout + result.stderr; log.write_text(text)
        if result.returncode: raise RuntimeError('failed command: ' + str(log))
        return text
    def fixture(path, changed=None):
        spec = generate(path, count, 'fan', changed=changed)
        (path / 'synthetic.json').unlink()  # Harness oracle is not a build input.
        props = path / 'Directory.Build.props'; props.write_text(props.read_text().replace('TargetFramework>', 'TargetFrameworks>'))
        run([DOTNET_ROOT / 'dotnet', 'msbuild', spec['entry'], '-t:Restore', '-p:Configuration=Release',
             '-p:TargetFramework=net10.0', '-nodeReuse:false', '-nologo'], path, path.parent / (path.name + '-restore.log'))
        return spec
    def shutdown(state):
        if (state / 'g').exists():
            subprocess.run([str(BAZEL), '--nohome_rc', '--noworkspace_rc', '--output_base=' + str(state / 'b'),
                '--output_user_root=' + str(state / 'u'), 'shutdown'], cwd=state / 'g', check=True, capture_output=True)
    try:
        with CacheServer(delay_ms=delay_ms) as server:
            endpoint = server.url + '/native'
            producer = output / 'p'; producer.mkdir(); spec = fixture(producer / 's')
            state = producer / 'state'; states.append(state)
            w = Workflow(producer / 's', state, spec['entry'], reuse=True, protected_store=ProtectedStore(), remote_endpoint=endpoint)
            baseline = w.run(producer / 'build'); assert baseline['compiles'] == count
            generation = json.loads((state / 'cache.json').read_text())['generation']
            contracts = {}
            for results in (state / 'cache' / generation).glob('*/results.json'):
                payload = json.loads(results.read_text())
                contracts[payload['project']] = dict(targets=payload['targets'], artifacts=json.loads((results.parent / 'artifacts.json').read_text()))
            (output / 'producer-contracts.json').write_text(json.dumps(contracts, sort_keys=True, indent=2))
            reference_oracle = {item['path']: item['sha256'] for contract in contracts.values()
                                for item in contract['artifacts'] if '/obj/Release/net10.0/ref/' in item['path']}
            assert len(reference_oracle) == count
            assert 'publishedSnapshot' in baseline['remote'], baseline['remote']
            base_snapshot = baseline['remote']['publishedSnapshot']
            report['producer'] = dict(snapshot=base_snapshot, projects=count, workflow=baseline, transport=server.totals())
            base_data = server.data.copy()
            shutdown(state); remove_tree(producer)
            assert not producer.exists(), 'producer must be absent before consumers'
            for repetition in range(repetitions):
                for case, changed in report['changedCases'].items():
                    base = output / f'{repetition}-{case[0]}'; base.mkdir()
                    src, raw_src = base / 's', base / 'r'; fixture(src, changed); fixture(raw_src, changed)
                    state = base / 'state'; states.append(state)
                    with server.lock: server.data = {} if case == 'empty' else base_data.copy()
                    event_start = len(server.events)
                    def native():
                        workflow = Workflow(src, state, spec['entry'], protected_store=ProtectedStore(),
                            remote_endpoint=endpoint, remote_snapshot_digest=base_snapshot if case != 'empty' else None)
                        result = workflow.run(base / 'native')
                        assert 'publishedSnapshot' in result['remote'], result['remote']
                        result['endToEndSeconds'] = result['seconds']
                        if case != 'empty':
                            assert not result['preparation']['discoveryExecuted'], result['preparation']
                            assert not result['remote']['seeds']['rejected'], result['remote']['seeds']
                        return result
                    def raw():
                        start = time.perf_counter()
                        log = run([DOTNET_ROOT / 'dotnet', 'msbuild', spec['entry'], '-t:Build', '-p:Configuration=Release',
                            '-p:TargetFramework=net10.0', '-p:PathMap=' + str(raw_src) + '=/_/workspace', '-graphBuild', '-isolateProjects',
                            '-m:2', '-nodeReuse:false', '-nologo', '-v:normal'], raw_src, base / 'raw.log')
                        return dict(seconds=time.perf_counter() - start,
                            compiles=sum('/Roslyn/bincore/csc' in line and ' /noconfig ' in line for line in log.splitlines()))
                    if repetition % 2: n, r = native(), raw()
                    else: r, n = raw(), native()
                    expected_projects = {str(Path(name(i)) / (name(i) + '.csproj')) for i in (range(count) if case == 'empty' else () if changed is None else (changed,))}
                    assert n['compiles'] == len(expected_projects), (case, n['compiles'], expected_projects)
                    assert r['compiles'] == count and n['buildActions'] == 1
                    events = json.loads((state / 'g/bazel-bin/build.diagnostics/events.json').read_text())
                    misses = {e['project'] for e in events if e['kind'] == 'miss'}
                    assert misses == expected_projects, (case, 'wrong projects recompiled', misses, expected_projects)
                    hits = [e for e in events if e['kind'] == 'hit']
                    assert len(hits) == count - len(expected_projects), (case, hits)
                    raw_runtime = raw_src / name(count - 1) / 'bin/Release/net10.0'
                    assert n['runtimeHashes'] == hashes(raw_runtime), (case, 'runtime mismatch')
                    references = {p.relative_to(raw_src).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in raw_src.glob('*/obj/Release/net10.0/ref/*.dll')}
                    assert len(references) == count
                    assert references == reference_oracle, 'body-only edit changed a reference assembly'
                    native_references = {p.relative_to(bundle / 'artifacts').as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                         for bundle in (state / 'g/bazel-bin/build.bundle/cache').iterdir()
                                         for p in (bundle / 'artifacts').glob('*/obj/Release/net10.0/ref/*.dll')}
                    assert native_references == references, 'native reference assemblies differ from raw'
                    for label, directory in (('raw', raw_runtime), ('native', state / 'g/bazel-bin/build.bundle/app')):
                        text = run([DOTNET_ROOT / 'dotnet', directory / (name(count - 1) + '.dll')], base, base / (label + '-run.log'))
                        assert text.strip() == oracle(spec['edges'], changed), (case, label, text)
                    transport = server.totals(event_start)
                    assert (case == 'empty' or transport['hits'] >= count) and transport['errors'] == 0
                    report['samples'].append(dict(repetition=repetition, case=case, native=n, raw=r,
                        expectedRecompiledProjects=sorted(expected_projects), cacheHits=len(hits), transport=transport,
                        referenceAssemblyCount=len(references), referenceHashesSha256=hashlib.sha256(json.dumps(references, sort_keys=True).encode()).hexdigest()))
                    save(); print(count, delay_ms, repetition, case, round(n['endToEndSeconds'],3), round(r['seconds'],3), n['compiles'], len(hits), flush=True)
                    shutdown(state)
            report['summary'] = []
            for case in report['changedCases']:
                rows = [s for s in report['samples'] if s['case'] == case]
                native = statistics.median(s['native']['endToEndSeconds'] for s in rows)
                raw = statistics.median(s['raw']['seconds'] for s in rows)
                report['summary'].append(dict(case=case, nativeMedian=native, rawMedian=raw, ratio=native/raw,
                    compiles=rows[0]['native']['compiles'], cacheHits=rows[0]['cacheHits'],
                    downloadBytesMedian=statistics.median(s['transport']['downloadBytes'] for s in rows),
                    uploadBytesMedian=statistics.median(s['transport']['uploadBytes'] for s in rows)))
            report['accepted'] = True; save()
    finally:
        save()
        for state in states: shutdown(state)
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True); p.add_argument('--count', type=int, default=100)
    p.add_argument('--repetitions', type=int, default=3); p.add_argument('--delay-ms', type=float, default=10)
    a = p.parse_args()
    if a.count < 3 or a.repetitions < 1 or a.delay_ms < 0: p.error('count >= 3, repetitions >= 1 and delay >= 0 required')
    measure(a.output.resolve(), a.count, a.repetitions, a.delay_ms)
