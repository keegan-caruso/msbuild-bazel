#!/usr/bin/env python3
"""C16 correctness smoke and retained protocol; not performance qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time

from prepare_graph import ROOT, DOTNET_ROOT, prepare
from probe_graph_execution import BAZEL
from probe_graph_cache import cache_environment
from probe_bazel import json_stream
from synthetic_graph import generate, name, project, source, consumers, oracle


def probe(output, count=10, shape='fan', cases=('fresh', 'warm', 'leaf', 'shared', 'recovery')):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    dotnet = DOTNET_ROOT / 'dotnet'
    strategy = 'darwin-sandbox' if platform.system() == 'Darwin' else 'linux-sandbox'
    phases = {}

    def run(label, command, cwd):
        started = time.monotonic()
        result = subprocess.run(list(map(str, command)), cwd=cwd, env=cache_environment(output, cwd),
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1800)
        phases[label] = dict(wallSeconds=time.monotonic() - started, processTreePeakBytes=None,
                             memoryStatus='unmeasured: no aggregate descendant RSS sampler')
        (output / (label + '.log')).write_text(result.stdout)
        if result.returncode: raise RuntimeError(label + ' failed; see ' + str(output / (label + '.log')))
        return result.stdout.strip()

    run('exporter-bootstrap', [dotnet, 'build', ROOT / 'tools/GraphExport', '-c', 'Release', '-nodeReuse:false', '--nologo'], ROOT)
    report = dict(schemaVersion=1, scope='R09-synthetic-correctness-smoke', count=count, shape=shape,
        performanceQualified=False, budgets=None, repetitions=1, jobs=2,
        platform=platform.platform(), architecture=platform.machine(), sdkRoot=str(DOTNET_ROOT),
        repositoryToolchainPins=json.loads((ROOT / 'scripts/toolchains.json').read_text()),
        serverPolicy='MSBuild node reuse and shared C# compiler disabled',
        timingStatus='descriptive wall times on shared worker; not benchmark comparisons',
        unmeasured=['aggregate process-tree RSS', 'separate evaluation/analysis/execution phase attribution',
                    'five interleaved repetitions', 'calibrated numeric qualification budgets', 'SDK acquisition cost'], cases={})
    for case in cases:
        state = output / case
        state.mkdir()
        ordinary = state / 'ordinary'
        spec = generate(ordinary, count, shape)
        edges, entry = spec['edges'], spec['entry']
        # Leaf means the final entry consumer; shared means the root dependency.
        changed = count - 1 if case == 'leaf' else 0 if case == 'shared' else None
        expected = oracle(edges, changed)
        ordinary_counts = []

        def restore(work, label):
            run(label, [dotnet, 'msbuild', entry, '-t:Restore', '-p:Configuration=Release', '-m:2', '-nodeReuse:false', '-nologo'], work)

        def ordinary_build(label):
            log = run(label, [dotnet, 'msbuild', entry, '-t:Build', '-p:Configuration=Release', '-graphBuild', '-isolateProjects',
                '-m:2', '-nodeReuse:false', '-nologo', '-verbosity:diagnostic', '-bl:' + str(output / (label + '.binlog'))], ordinary)
            # Diagnostic task-start lines distinguish executed Csc tasks from skipped targets.
            return len(re.findall(r'Task "Csc"\s+\(TaskId:\d+\)', log))

        restore(ordinary, case + '-ordinary-restore')
        if case != 'fresh':
            ordinary_counts.append(ordinary_build(case + '-ordinary-warmup'))
            if ordinary_counts != [count]: raise AssertionError('ordinary baseline warmup did not compile every node')
        if changed is not None:
            (ordinary / name(changed) / 'Value.cs').write_text(source(changed, edges[changed], changed == count - 1, True))
        if case == 'recovery':
            for i in range(count):
                for directory in ('bin', 'obj/Release'):
                    shutil.rmtree(ordinary / name(i) / directory, ignore_errors=True)
        ordinary_count = ordinary_build(case + '-ordinary')
        ordinary_result = run(case + '-ordinary-app', [dotnet, ordinary / name(count - 1) / f'bin/Release/net10.0/{name(count - 1)}.dll'], ordinary)
        if ordinary_result != expected: raise AssertionError('ordinary output mismatch ' + case)
        ordinary_expected = count if case in ('fresh', 'recovery') else 0 if case == 'warm' else 1
        if ordinary_count != ordinary_expected:
            raise AssertionError(f'{case}: ordinary Csc count {ordinary_count}, expected {ordinary_expected}')
        preparation, generated = state / 'preparation', state / 'generated'
        generate(preparation, count, shape)
        restore(preparation, case + '-adapter-restore')

        def publish(label):
            manifest, request = output / (label + '-manifest.json'), output / (label + '-request.json')
            request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(preparation), dotnetRoot=str(DOTNET_ROOT),
                sdkVersion='10.0.100', packageRoot=str(preparation / '.nuget/packages'),
                entryPoints=[dict(project=entry, globalProperties={'Configuration': 'Release'})], output=str(manifest))))
            run(label + '-export', [dotnet, ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], preparation)
            started = time.monotonic()
            graph = prepare(preparation, manifest, generated, environment=cache_environment(output, preparation))
            actual_nodes = {n['id']: n for n in graph['nodes']}
            actual_edges = {n['project'].removeprefix('workspace/'): sorted(actual_nodes[d]['project'].removeprefix('workspace/') for d in n['dependencies']) for n in graph['nodes']}
            if actual_edges != {project(i): sorted(project(d) for d in dependencies) for i, dependencies in enumerate(edges)}:
                raise AssertionError('exported configured graph differs from generated topology')
            phases[label + '-prepare'] = dict(wallSeconds=time.monotonic() - started, processTreePeakBytes=None,
                memoryStatus='unmeasured: no aggregate descendant RSS sampler')
            return graph

        graph = publish(case + '-baseline')
        base, cache = state / 'output-base', state / 'disk-cache'
        def build(label):
            execution = output / (label + '-execution.json')
            profile = output / (label + '-profile.json.gz')
            run(label, [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc', '--output_base=' + str(base),
                '--output_user_root=' + str(state / 'bazel-user'), 'build', '//:all',
                *['//:node_' + node['id'] for node in graph['nodes']], '--disk_cache=' + str(cache),
                '--spawn_strategy=' + strategy, '--strategy=MsbuildProject=' + strategy,
                '--jobs=2', '--noshow_progress', '--color=no', '--curses=no',
                '--execution_log_json_file=' + str(execution), '--profile=' + str(profile)], generated)
            lookup = {node['id']: node for node in graph['nodes']}
            actions = []
            for record in json_stream(execution):
                if record.get('mnemonic') != 'MsbuildProject': continue
                identity = record['targetLabel'].split(':node_')[-1]
                action = dict(nodeId=identity, project=lookup[identity]['project'].removeprefix('workspace/'),
                    cacheHit=record.get('cacheHit', False), runner=record.get('runner'))
                if not action['cacheHit']:
                    diagnostic = generated / f'bazel-bin/node_{identity}.diagnostics'
                    retained = output / (label + '-' + identity + '.build.log')
                    shutil.copyfile(diagnostic / 'build.log', retained)
                    action['log'] = retained.name
                    detail = json.loads((diagnostic / 'action.json').read_text())
                    action['compiledProjects'] = detail['compiledProjects']
                    if detail['compiledProjects'] != [Path(action['project']).stem]: raise AssertionError('unexpected compilation')
                    if action['runner'] != strategy: raise AssertionError('not native sandbox')
                actions.append(action)
            app = next(node for node in graph['nodes'] if node['project'] == 'workspace/' + entry)
            actual = run(label + '-app', [dotnet, generated / f'bazel-bin/node_{app["id"]}.bundle/artifacts' / name(count - 1) / f'bin/Release/net10.0/{name(count - 1)}.dll'], generated)
            bundle_files = {}
            for node in graph['nodes']:
                bundle = generated / f'bazel-bin/node_{node["id"]}.bundle'
                if not bundle.is_dir(): raise AssertionError('missing bundle')
                for path in sorted(bundle.rglob('*')):
                    if path.is_file(): bundle_files[node['id'] + '/' + path.relative_to(bundle).as_posix()] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(), executable=bool(path.stat().st_mode & 0o111))
            return dict(output=actual, actions=actions, bundleFiles=bundle_files, executionLog=execution.name, profile=profile.name)

        warmup = None
        if case != 'fresh':
            warmup = build(case + '-adapter-warmup')
            if warmup['output'] != oracle(edges) or {a['project'] for a in warmup['actions'] if not a['cacheHit']} != {project(i) for i in range(count)}:
                raise AssertionError('adapter baseline warmup was not a correct full fresh build')
        if changed is not None:
            (preparation / name(changed) / 'Value.cs').write_text(source(changed, edges[changed], changed == count - 1, True))
            shutil.rmtree(generated)
            graph = publish(case + '-changed')
        if case == 'recovery':
            for directory in (base, generated):
                for path in directory.rglob('*'):
                    if path.is_dir() and not path.is_symlink(): path.chmod(path.stat().st_mode | 0o700)
                shutil.rmtree(directory)
            graph = publish(case + '-recovery')
        shutil.rmtree(preparation)
        record = build(case + '-adapter')
        expected_actions = {project(i) for i in (range(count) if case == 'fresh' else consumers(edges, changed) if changed is not None else [])}
        actual_actions = {a['project'] for a in record['actions'] if not a['cacheHit']}
        if actual_actions != expected_actions or len([a for a in record['actions'] if not a['cacheHit']]) != len(expected_actions): raise AssertionError(f'{case}: adapter action set mismatch {actual_actions} != {expected_actions}')
        if record['output'] != expected: raise AssertionError('adapter output mismatch')
        if case == 'recovery':
            if {a['project'] for a in record['actions'] if a['cacheHit']} != {project(i) for i in range(count)}: raise AssertionError('recovery missed disk hits')
            if any(a['runner'] != 'disk cache hit' for a in record['actions']): raise AssertionError('recovery did not use disk cache')
            if record['bundleFiles'] != warmup['bundleFiles']: raise AssertionError('recovered bundle bytes changed')
        record.update(expectedOutput=expected, expectedExecutedProjects=sorted(expected_actions),
            ordinaryOutput=ordinary_result, ordinaryCompilerInvocations=ordinary_count, expectedOrdinaryCompilerInvocations=ordinary_expected,
            ordinaryWarmupCompilerInvocations=ordinary_counts, nodeCount=len(graph['nodes']), edgeCount=sum(len(n['dependencies']) for n in graph['nodes']),
            preparationWorkspaceAbsent=not preparation.exists(), baselineWarmup=warmup)
        report['cases'][case] = record
    report['phases'] = phases
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--nodes', type=int, default=10)
    parser.add_argument('--shape', choices=('chain', 'fan'), default='fan')
    parser.add_argument('--cases', nargs='+', choices=('fresh', 'warm', 'leaf', 'shared', 'recovery'), default=['fresh', 'warm', 'leaf', 'shared', 'recovery'])
    args = parser.parse_args()
    probe(args.output, args.nodes, args.shape, args.cases)
