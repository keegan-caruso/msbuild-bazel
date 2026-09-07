#!/usr/bin/env python3
"""R03 native configured-node acceptance, with retained manifests and bundle bytes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from prepare_graph import prepare, ROOT, DOTNET_ROOT
from probe_graph_execution import BAZEL
from probe_graph_cache import run_logged, cache_environment
from probe_bazel import json_stream


def probe(output, scope='inner'):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    dotnet = DOTNET_ROOT / 'dotnet'
    strategy = 'darwin-sandbox' if platform.system() == 'Darwin' else 'linux-sandbox'
    base, cache = output / 'bazel-base', output / 'disk-cache'
    entry = 'Multi/Multi.csproj' if scope == 'inner' else 'build.proj'
    app_project = 'Multi/Multi.csproj' if scope == 'inner' else 'App/App.csproj'
    properties = {'Configuration': 'Release'}
    if scope == 'inner': properties['TargetFramework'] = 'net10.0'
    arguments = ['-p:' + k + '=' + v for k, v in properties.items()]

    def run(name, args, cwd):
        return run_logged(output, name, args, cwd)

    def fixture(path):
        shutil.copytree(ROOT / 'tests/fixtures/configured-nodes', path)
        (path / '.nuget/packages').mkdir(parents=True, exist_ok=True)

    def export(source, name, export_entry=entry, export_properties=None):
        selected = properties if export_properties is None else export_properties
        manifest = output / (name + '-manifest.json')
        request = output / (name + '-request.json')
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(source),
            dotnetRoot=str(DOTNET_ROOT), sdkVersion='10.0.100', packageRoot=str(source / '.nuget/packages'),
            entryPoints=[dict(project=export_entry, globalProperties=selected)], output=str(manifest))))
        run(name + '-export', [dotnet, ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], source)
        return manifest

    def restore(source, name):
        run(name + '-restore', [dotnet, 'msbuild', entry, '-t:Restore', *arguments, '-nodeReuse:false', '-nologo'], source)
        if scope == 'configured':
            for flavor in ('red', 'blue'):
                run(name + '-restore-' + flavor, [dotnet, 'msbuild', 'Shared/Shared.csproj',
                    '-t:Restore', '-p:Configuration=Release', '-p:Flavor=' + flavor, '-nodeReuse:false', '-nologo'], source)

    def generate(source, generated, name):
        restore(source, name)
        manifest = export(source, name)
        if generated.exists(): shutil.rmtree(generated)
        graph = prepare(source, manifest, generated, environment=cache_environment(output, source))
        return graph

    def bazel(generated, name, command):
        return run(name, [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc',
            '--output_base=' + str(base), '--output_user_root=' + str(output / 'bazel-user'), *command], generated)

    def build(generated, graph, name, **extra):
        execution = output / (name + '-execution.json')
        # Request every node so recovered dependency bundle bytes are materialized,
        # even when a cached entry action no longer needs its inputs locally.
        targets = ['//:node_' + node['id'] for node in graph['nodes']]
        bazel(generated, name, ['build', '//:all', *targets, '--disk_cache=' + str(cache),
            '--spawn_strategy=' + strategy, '--strategy=MsbuildProject=' + strategy,
            '--jobs=2', '--noshow_progress', '--color=no', '--curses=no',
            '--execution_log_json_file=' + str(execution)])
        retained = output / 'evidence' / name
        retained.mkdir(parents=True)
        nodes = {node['id']: node for node in graph['nodes']}
        actions = []
        for record in json_stream(execution):
            if record.get('mnemonic') != 'MsbuildProject': continue
            identity = record['targetLabel'].split(':node_')[-1]
            action = dict(nodeId=identity, project=nodes[identity]['project'],
                properties=nodes[identity]['globalProperties'], runner=record.get('runner'),
                cacheHit=record.get('cacheHit', False), remotable=record.get('remotable'),
                remoteCacheable=record.get('remoteCacheable'))
            if not action['cacheHit']:
                log = retained / (identity + '.log')
                shutil.copyfile(generated / f'bazel-bin/node_{identity}.diagnostics/build.log', log)
                action['log'] = log.relative_to(output).as_posix()
                detail = json.loads((generated / f'bazel-bin/node_{identity}.diagnostics/action.json').read_text())
                action['compiledProjects'] = detail['compiledProjects']
                action['replayHits'] = detail['replayHits']
            actions.append(action)
        files = {}
        for identity in nodes:
            bundle = generated / f'bazel-bin/node_{identity}.bundle'
            if not bundle.is_dir(): raise RuntimeError('missing configured bundle ' + identity)
            for path in sorted(bundle.rglob('*')):
                if not path.is_file(): continue
                logical = identity + '/' + path.relative_to(bundle).as_posix()
                target = retained / 'bundles' / logical
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, target)
                files[logical] = dict(file=target.relative_to(output).as_posix(),
                    sha256=hashlib.sha256(target.read_bytes()).hexdigest(), executable=bool(target.stat().st_mode & 0o111))
        app = next(n for n in nodes.values() if n['project'] == 'workspace/' + app_project)
        assembly = next(o['path'].removeprefix('workspace/') for o in app['outputs'] if o['kind'] == 'assembly')
        actual = run(name + '-app', [dotnet, generated / f'bazel-bin/node_{app["id"]}.bundle/artifacts' / assembly], generated)
        canonical = {name: {k: info[k] for k in ('sha256', 'executable')} for name, info in files.items()}
        return dict(actions=actions, output=actual, nodes=nodes, bundleFiles=files,
            bundleDigest=hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
            executionLog=execution.name, **extra)

    run('exporter-build', [dotnet, 'build', ROOT / 'tools/GraphExport', '-c', 'Release', '-nodeReuse:false', '--nologo'], ROOT)
    ordinary = output / 'ordinary'
    fixture(ordinary)
    restore(ordinary, 'ordinary')
    run('ordinary-build', [dotnet, 'msbuild', entry, '-t:Build', *arguments,
        '-graphBuild', '-isolateProjects', '-nodeReuse:false', '-nologo'], ordinary)
    binary = Path(app_project).parent / ('bin/Release/net10.0/' + Path(app_project).stem + '.dll')
    baseline = run('ordinary-app', [dotnet, ordinary / binary], ordinary)
    shutil.rmtree(ordinary)
    source, generated = output / 'preparation', output / 'workspace'
    fixture(source)
    graph = generate(source, generated, 'cold')
    shutil.rmtree(source)
    cases = {'cold': build(generated, graph, 'cold', preparationWorkspaceAbsent=not source.exists())}
    cases['unchanged'] = build(generated, graph, 'unchanged')
    if scope == 'configured':
        fixture(source)
        path = source / 'Right/Right.csproj'
        path.write_text(path.read_text().replace('Flavor=blue', 'Flavor=red'))
        graph = generate(source, generated, 'edge-converged')
        analysis = bazel(generated, 'edge-analysis', ['query', 'kind(graph_project, //:*)', '--output=xml', '--noshow_progress'])
        import xml.etree.ElementTree as ET
        analyzed = {}
        for rule in ET.fromstring(analysis).findall('rule'):
            dependencies = rule.find("list[@name='dependencies']")
            analyzed[rule.attrib['name'].split(':node_')[-1]] = sorted(
                item.attrib['value'].split(':node_')[-1] for item in ([] if dependencies is None else dependencies))
        shutil.rmtree(source)
        cases['edgeConverged'] = build(generated, graph, 'edgeConverged', analyzedDependencies=analyzed)
        fixture(source)
        graph = generate(source, generated, 'recovery-baseline')
        shutil.rmtree(source)
        build(generated, graph, 'recovery-baseline')
    for directory, _, _ in os.walk(base, followlinks=False):
        path = Path(directory)
        if not path.is_symlink(): path.chmod(path.stat().st_mode | 0o700)
    shutil.rmtree(base)
    shutil.rmtree(generated)
    relocated_source, relocated = output / 'relocated-preparation', output / 'relocated-workspace'
    fixture(relocated_source)
    graph = generate(relocated_source, relocated, 'relocated')
    shutil.rmtree(relocated_source)
    cases['relocated'] = build(relocated, graph, 'relocated',
        outputBaseAbsentBeforeBuild=not base.exists(), producerWorkspaceAbsent=not source.exists() and not generated.exists(),
        preparationWorkspaceAbsent=not relocated_source.exists(), outputsAbsentBeforeBuild=not list(relocated.glob('bazel-*')))
    failures = {}
    for name in (['outer'] if scope == 'inner' else ['outer', 'defaultTransitive']):
        rejected_source = output / (name + '-source')
        fixture(rejected_source)
        restore(rejected_source, name)
        rejected_entry = 'Multi/Multi.csproj' if name == 'outer' else 'build.proj'
        if name == 'defaultTransitive':
            props = rejected_source / 'Directory.Build.props'
            props.write_text(props.read_text().replace(
                '<DisableTransitiveProjectReferences>true</DisableTransitiveProjectReferences>', ''))
            restore(rejected_source, name + '-default')
        manifest = output / (name + '-rejected.json')
        request = output / (name + '-rejected-request.json')
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(rejected_source),
            dotnetRoot=str(DOTNET_ROOT), sdkVersion='10.0.100', packageRoot=str(rejected_source / '.nuget/packages'),
            entryPoints=[dict(project=rejected_entry, globalProperties={'Configuration': 'Release'})], output=str(manifest))))
        result = subprocess.run([str(dotnet), str(ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll'),
            '--request', str(request)], cwd=rejected_source, env=cache_environment(output, rejected_source),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        log = output / (name + '-rejection.log')
        log.write_text(result.stdout)
        failures[name] = dict(returncode=result.returncode, publishedManifest=manifest.exists(), log=log.name)
    report = dict(schemaVersion=1, scope=scope, baselineOutput=baseline, cases=cases, failures=failures)
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--scope', choices=('inner', 'configured'), default='inner')
    args = parser.parse_args()
    probe(args.output, args.scope)
