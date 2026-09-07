#!/usr/bin/env python3
"""R01 package-free generated graph cache evidence; R02 packages remain separate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

from probe_graph_execution import BAZEL, DOTNET_ROOT, ROOT, write_fixture
from prepare_graph import prepare
from probe_bazel import json_stream


def cache_environment(output, workspace):
    """Keep NuGet configuration stable and never inherit an old MSBuild worker."""
    return dict(os.environ, NUGET_PACKAGES=str(workspace / '.nuget/packages'),
                DOTNET_CLI_HOME=str(output / 'home'), DOTNET_NOLOGO='1',
                DOTNET_CLI_TELEMETRY_OPTOUT='1', MSBUILDDISABLENODEREUSE='1')


def run_logged(output, name, args, cwd):
    result = subprocess.run(list(map(str, args)), cwd=cwd, env=cache_environment(output, cwd),
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    (output / (name + '.log')).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(name + ' failed: ' + result.stdout + result.stderr)
    return result.stdout.strip()


def restore_source(output, source, name):
    return run_logged(output, name, [DOTNET_ROOT / 'dotnet', 'msbuild', 'build.proj',
        '-t:Restore', '-p:Configuration=Release', '-nodeReuse:false', '-nologo'], source)


def probe(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    dotnet = DOTNET_ROOT / 'dotnet'
    serial = 0
    def run(name, args, cwd):
        return run_logged(output, name, args, cwd)

    def fixture(path):
        write_fixture(path)
        (path / 'src/App/Program.cs').write_text('''var suffix = "";
#if CACHE_CONFIG_V2
suffix = "|config-v2";
#endif
Console.WriteLine(Left.Value.Text + "|" + Right.Value.Text + suffix);
''')
        (path / '.nuget/packages').mkdir(parents=True, exist_ok=True)

    def export(source, name):
        nonlocal serial
        restore_source(output, source, name + '-restore')
        manifest = output / (name + '-manifest.json')
        request = output / (name + '-request.json')
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(source), dotnetRoot=str(DOTNET_ROOT),
            sdkVersion='10.0.100', packageRoot=str(source / '.nuget/packages'),
            entryPoints=[dict(project='build.proj', globalProperties={'Configuration':'Release'})], output=str(manifest))))
        run(name + '-export', [dotnet, ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], source)
        return manifest

    def generate(source, generated, name):
        nonlocal serial
        manifest = export(source, name)
        if generated.exists(): shutil.rmtree(generated)
        graph = prepare(source, manifest, generated, environment=cache_environment(output, source))
        serial += 1
        return graph, manifest

    strategy = 'darwin-sandbox' if platform.system() == 'Darwin' else 'linux-sandbox'
    def remove_output_base():
        # Bazel protects output directories; never follow toolchain symlinks.
        for directory, _, _ in os.walk(base, followlinks=False):
            path = Path(directory)
            if not path.is_symlink(): path.chmod(path.stat().st_mode | 0o700)
        shutil.rmtree(base)

    cache = output / 'disk-cache'
    base = output / 'bazel-base'
    def bazel(generated, name, command):
        return run(name, [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc',
            f'--output_base={base}', f'--output_user_root={output / "bazel-user"}', *command], generated)

    def build(generated, graph, name, **extra):
        execution = output / (name + '-execution.json')
        bazel(generated, name, ['build', '//:all', f'--disk_cache={cache}',
            f'--spawn_strategy={strategy}', f'--strategy=MsbuildProject={strategy}', '--jobs=2',
            '--noshow_progress', '--color=no', '--curses=no', '--remote_download_outputs=all', f'--execution_log_json_file={execution}'])
        nodes = {n['id']: n['project'].removeprefix('workspace/') for n in graph['nodes']}
        retained = output / 'evidence' / name
        retained.mkdir(parents=True)
        shutil.copytree(generated / 'restore', retained / 'restore')
        executions = []
        for record in json_stream(execution):
            if record.get('mnemonic') != 'MsbuildProject': continue
            identity = record['targetLabel'].split(':node_')[-1]
            action = dict(nodeId=identity, project=nodes[identity], cacheHit=record.get('cacheHit', False),
                runner=record.get('runner'), remotable=record.get('remotable'), remoteCacheable=record.get('remoteCacheable'))
            if not action['cacheHit']:
                log = retained / (identity + '.log')
                shutil.copyfile(generated / f'bazel-bin/node_{identity}.diagnostics/build.log', log)
                action['log'] = log.relative_to(output).as_posix()
            executions.append(action)
        bundle_files = {}
        for identity in nodes:
            bundle = generated / f'bazel-bin/node_{identity}.bundle'
            if not bundle.is_dir():
                raise RuntimeError('configured bundle was not materialized: ' + identity)
            for source in sorted(bundle.rglob('*')):
                if not source.is_file(): continue
                logical = f'node_{identity}/' + source.relative_to(bundle).as_posix()
                target = retained / 'bundles' / logical
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                bundle_files[logical] = dict(file=target.relative_to(output).as_posix(),
                    sha256=hashlib.sha256(target.read_bytes()).hexdigest(), executable=bool(target.stat().st_mode & 0o111))
        canonical = {p: {k: m[k] for k in ('sha256', 'executable')} for p, m in bundle_files.items()}
        app = next(i for i, p in nodes.items() if p == 'src/App/App.csproj')
        actual = run(name + '-app', [dotnet, generated / f'bazel-bin/node_{app}.bundle/artifacts/src/App/bin/Release/net10.0/App.dll'], generated)
        return dict(returncode=0, applicationReturncode=0, applicationOutput=actual,
            executedProjects=sorted(a['project'] for a in executions if not a['cacheHit']),
            cacheHitProjects=sorted(a['project'] for a in executions if a['cacheHit']), executions=executions,
            executionLog=execution.relative_to(output).as_posix(), bundleFiles=bundle_files,
            bundleDigest=hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest(), **extra)

    run('exporter-build', [dotnet, 'build', ROOT / 'tools/GraphExport', '-c', 'Release', '--nologo'], ROOT)
    ordinary = output / 'ordinary'
    fixture(ordinary)
    export(ordinary, 'ordinary')
    run('ordinary-build', [dotnet, 'msbuild', 'build.proj', '-t:Build', '-p:Configuration=Release', '-graphBuild', '-isolateProjects', '-nologo'], ordinary)
    baseline = run('ordinary-app', [dotnet, ordinary / 'src/App/bin/Release/net10.0/App.dll'], ordinary)
    shutil.rmtree(ordinary)
    source, generated = output / 'preparation', output / 'workspace'
    fixture(source)
    graph, before_manifest = generate(source, generated, 'cold')
    cases = {'cold': build(generated, graph, 'cold')}
    cases['unchanged'] = build(generated, graph, 'unchanged')
    mutations = {
        'appEdit': ('src/App/Program.cs', ' + suffix)', ' + suffix + "|app-v2")'),
        'leftEdit': ('src/Left/Value.cs', ':left"', ':left-v2"'),
        'sharedEdit': ('src/Shared/Message.cs', 'shared-v1', 'shared-v2'),
        'importEdit': ('Directory.Build.props', '</PropertyGroup>', '<DefineConstants>$(DefineConstants);CACHE_CONFIG_V2</DefineConstants></PropertyGroup>'),
        'graphEdgeAdded': ('src/Right/Right.csproj', '</ItemGroup>', '<ProjectReference Include="../Left/Left.csproj"/></ItemGroup>'),
    }
    edge = None
    for name, (path, old, new) in mutations.items():
        # Reset and warm the exact baseline before each independent perturbation.
        shutil.rmtree(source)
        fixture(source)
        graph, before = generate(source, generated, name + '-baseline')
        build(generated, graph, name + '-baseline')
        target = source / path
        target.write_text(target.read_text().replace(old, new))
        if name == 'graphEdgeAdded':
            target = source / 'src/Right/Value.cs'
            target.write_text(target.read_text().replace(' + ":right"', ' + ":right+" + Left.Value.Text'))
        graph, after = generate(source, generated, name)
        if name == 'graphEdgeAdded':
            generation = serial
            analysis = bazel(generated, 'edge-analysis', ['query', 'kind(graph_project, //:*)', '--output=xml', '--noshow_progress'])
            import xml.etree.ElementTree as ET
            analyzed = {}
            for rule in ET.fromstring(analysis).findall('rule'):
                dependencies = rule.find("list[@name='dependencies']")
                analyzed[rule.attrib['name'].split(':node_')[-1]] = sorted(v.attrib['value'].split(':node_')[-1] for v in ([] if dependencies is None else dependencies))
            serial += 1
            edge = dict(beforeManifest=before.name, afterManifest=after.name, analysisLog='edge-analysis.log',
                analyzedDependencies=analyzed, planGenerationSequence=generation, analysisSequence=serial)
        cases[name] = build(generated, graph, name)
        if name == 'sharedEdit':
            control = output / 'ordinary-shared-edit'
            fixture(control)
            target = control / path
            target.write_text(target.read_text().replace(old, new))
            export(control, 'ordinary-shared-edit')
            run('ordinary-shared-edit-build', [dotnet, 'msbuild', 'build.proj', '-t:Build',
                '-p:Configuration=Release', '-graphBuild', '-isolateProjects', '-nologo'], control)
            cases[name]['ordinaryOutput'] = run('ordinary-shared-edit-app',
                [dotnet, control / 'src/App/bin/Release/net10.0/App.dll'], control)
            shutil.rmtree(control)
    shutil.rmtree(source)
    fixture(source)
    graph, _ = generate(source, generated, 'recovery-baseline')
    build(generated, graph, 'recovery-baseline')
    remove_output_base()
    # Regenerate from restored source, dropping every prior output symlink/product.
    graph, _ = generate(source, generated, 'recovery')
    absent = not list(generated.glob('bazel-*')) and not list(source.glob('src/*/bin'))
    cases['diskCache'] = build(generated, graph, 'diskCache', outputsAbsentBeforeBuild=absent, outputBaseAbsentBeforeBuild=not base.exists())
    remove_output_base()
    shutil.rmtree(generated)
    shutil.rmtree(source)
    relocated_source, relocated = output / 'relocated-preparation', output / 'relocated-workspace'
    fixture(relocated_source)
    graph, _ = generate(relocated_source, relocated, 'relocated')
    shutil.rmtree(relocated_source)
    cases['relocated'] = build(relocated, graph, 'relocated', outputsAbsentBeforeBuild=not list(relocated.glob('bazel-*')),
        outputBaseAbsentBeforeBuild=not base.exists(), producerWorkspaceAbsent=not source.exists() and not generated.exists(),
        producerWorkspace=str(generated), consumerWorkspace=str(relocated))
    report = dict(schemaVersion=1, scope='R01-package-free-cache', baselineOutput=baseline, cases=cases, graphEdgeAdded=edge,
        pendingTracks=['R01-handoff-controls', 'R02-managed-packages'])
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = probe(args.output)
    print(json.dumps({k: v for k, v in result.items() if k != 'cases'}, indent=2))
