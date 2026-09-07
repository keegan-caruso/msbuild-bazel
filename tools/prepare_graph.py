#!/usr/bin/env python3
"""Materialize the supported local graph slice as Bazel configured project actions."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile

import graph_packages

ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = Path(os.environ.get('SPIKE_DOTNET_ROOT', ROOT / '.tools/dotnet')).resolve()


def relative(value):
    if not value.startswith('workspace/'):
        raise ValueError('expected workspace path: ' + value)
    result = value.removeprefix('workspace/')
    if not result or Path(result).is_absolute() or '..' in Path(result).parts:
        raise ValueError('unsafe workspace path: ' + value)
    return result


def prepare(workspace, manifest, output, *, environment=None):
    """Publish only a completely validated plan; serialize shared adapter builds."""
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    lock = ROOT / 'artifacts/graph-preparation.lock'
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open('a') as handle, tempfile.TemporaryDirectory(prefix='.graph-prepare-', dir=output.parent) as temporary:
        fcntl.flock(handle, fcntl.LOCK_EX)
        staged = Path(temporary) / 'workspace'
        graph = _prepare(workspace, manifest, staged, environment=environment)
        # Never replace another preparation's committed plan, including an empty directory.
        if output.exists():
            raise FileExistsError(output)
        staged.rename(output)
        return graph


def _prepare(workspace, manifest, output, *, environment=None):
    workspace, manifest, output = map(lambda p: Path(p).resolve(), (workspace, manifest, output))
    graph = json.loads(manifest.read_text())
    if graph['schemaVersion'] != 1 or graph.get('toolchain') != {'sdkVersion': '10.0.100', 'graphEngine': 'ProjectGraph', 'contractVersion': 1}:
        raise ValueError('unsupported graph schema')
    nodes = {n['id']: n for n in graph['nodes']}
    if len(nodes) != len(graph['nodes']) or not nodes or len({n['project'] for n in nodes.values()}) != len(nodes):
        raise ValueError('duplicate or empty graph nodes')
    for node in nodes.values():
        if not re.fullmatch('[0-9a-f]{24}', node['id']):
            raise ValueError('invalid configured node id')
        if node['globalProperties'] not in ({'configuration': 'Release'}, {'configuration': 'Release', 'targetframework': 'net10.0'}) or node['targetFramework'] != 'net10.0':
            raise ValueError('unsupported graph execution configuration')
        project = relative(node['project'])
        expected = str(Path(project).parent / 'bin/Release/net10.0' / (Path(project).stem + '.dll'))
        if node['outputs'] != [{'kind': 'assembly', 'path': 'workspace/' + expected}]:
            raise ValueError('unsupported graph output layout')
        if any(dep not in nodes for dep in node['dependencies']):
            raise ValueError('missing dependency node')
        assets = json.loads((workspace / Path(project).parent / 'obj/project.assets.json').read_text())
        graph_packages.package_plan(workspace, project)
    def closure(identity, active=()):
        if identity in active:
            raise ValueError('cyclic graph')
        result = {identity}
        for dependency in nodes[identity]['dependencies']:
            result.update(closure(dependency, (*active, identity)))
        return result
    closures = {identity: closure(identity) for identity in nodes}
    if not graph['entryPoints'] or any(entry not in nodes for entry in graph['entryPoints']):
        raise ValueError('invalid entry points')
    # Check every exported file against the producer manifest before publishing.
    # Match the exporter's normalization, including NuGet's derived dgspec hash.
    roots = {'workspace': workspace, 'dotnet': DOTNET_ROOT,
             'packages': workspace / '.nuget/packages', 'adapter': ROOT / 'tools/GraphExport'}
    inputs = graph.get('graphInputs', []) + [item for node in nodes.values() for item in node['inputs']]
    for item in inputs:
        prefix, _, logical = item['path'].partition('/')
        if prefix not in roots or not logical or Path(logical).is_absolute() or '..' in Path(logical).parts:
            raise ValueError('unsafe input path: ' + item['path'])
        source = roots[prefix] / logical
        # SDK installations may contain Nix symlinks; workspace payloads may not escape.
        if not source.is_file() or (prefix == 'workspace' and not source.resolve().is_relative_to(workspace)):
            raise ValueError('missing-input: missing or escaping input: ' + item['path'])
        if prefix == 'workspace' and '/obj/' in '/' + logical and item['kind'] not in ('restore', 'import'):
            raise ValueError('unsupported declared obj input: ' + item['path'])
        contents = source.read_bytes()
        if item['kind'] == 'restore' or (item['kind'] == 'import' and source.suffix.lower() in ('.json', '.props', '.targets', '.xml', '.proj', '.csproj')):
            text = source.read_text()
            if source.name == 'project.nuget.cache':
                cache = json.loads(text)
                if 'dgSpecHash' in cache: cache['dgSpecHash'] = '$NORMALIZED'
                text = json.dumps(cache, separators=(',', ':'), ensure_ascii=True)
                # System.Text.Json's default encoder escapes HTML-sensitive ASCII.
                for character in ('<', '>', '&', "'", '+'):
                    text = text.replace(character, '\\u' + format(ord(character), '04X'))
            contents = text.replace(str(workspace), '$WORKSPACE').replace(str(workspace / '.nuget/packages'), '$PACKAGES').replace(str(DOTNET_ROOT), '$DOTNET').encode()
        if hashlib.sha256(contents).hexdigest() != item['sha256']:
            raise ValueError(('hash-mismatch: ' if item['kind'] == 'package' else 'stale-manifest: ') + 'stale graph input: ' + item['path'])
    if not graph.get('entryRequests'):
        raise ValueError('graph discovery request missing; regenerate manifest')
    output.mkdir(parents=True, exist_ok=False)
    for name in ('GraphExport', 'ReplayPlugin', 'ActionRunner'):
        result = subprocess.run([str(DOTNET_ROOT / 'dotnet'), 'build', str(ROOT / 'tools' / name), '-c', 'Release', '--nologo'], cwd=ROOT, text=True, capture_output=True, env=environment)
        (output / (name + '-build.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(name + ' build failed: ' + result.stdout + result.stderr)
    # Hashes cover present inputs only. Re-evaluation also discovers new globs,
    # previously absent imports and changed conditional project references.
    request = output.parent / 'discovery-request.json'
    refreshed = output.parent / 'discovery.json'
    request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(workspace),
        dotnetRoot=str(DOTNET_ROOT), sdkVersion='10.0.100',
        packageRoot=str(workspace / '.nuget/packages'),
        entryPoints=graph['entryRequests'], output=str(refreshed))))
    result = subprocess.run([str(DOTNET_ROOT / 'dotnet'),
        str(ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll'),
        '--request', str(request)], cwd=workspace, text=True, capture_output=True, env=environment)
    if result.returncode:
        raise ValueError('graph discovery revalidation failed: ' + result.stdout + result.stderr)
    if json.loads(refreshed.read_text()) != graph:
        raise ValueError('stale-manifest: stale graph discovery: regenerate manifest')
    shutil.copyfile(ROOT / 'tools/ReplayPlugin/bin/Release/net10.0/ReplayPlugin.dll', output / 'ReplayPlugin.dll')
    (output / 'runner').mkdir()
    for suffix in ('.dll', '.deps.json', '.runtimeconfig.json'):
        shutil.copyfile(ROOT / ('tools/ActionRunner/bin/Release/net10.0/ActionRunner' + suffix), output / ('runner/ActionRunner' + suffix))
    for name in ('Action.props', 'Action.targets'):
        contents = (ROOT / 'tools/ActionRunner/Build' / name).read_text()
        filename = 'Directory.Build.' + ('props' if name.endswith('.props') else 'targets')
        property_name = '_GraphDirectoryBuild' + ('Props' if name.endswith('.props') else 'Targets')
        import_path = "$([MSBuild]::GetPathOfFileAbove('" + filename + "', '$(MSBuildProjectDirectory)/'))"
        original = '<Import Project="$(SPIKE_REPLAY_WORKSPACE)/' + filename + '" />'
        replacement = '<PropertyGroup><' + property_name + '>' + import_path + '</' + property_name + '></PropertyGroup>'
        replacement += '<Import Project="$(' + property_name + ')" Condition="\'$(' + property_name + ')\' != \'\'" />'
        contents = contents.replace(original, replacement)
        (output / 'runner' / name).write_text(contents)
    # Instrument every subject regardless of fixture naming or project directory.
    targets = output / 'runner/Action.targets'
    targets.write_text(targets.read_text().replace('</Project>', '<Target Name="GraphCompileEvidence" BeforeTargets="CoreCompile"><Message Importance="high" Text="SPIKE_COMPILE:$(SPIKE_GRAPH_PROJECT)" /></Target></Project>'))
    for name in ('msbuild.bzl', 'graph.bzl'):
        shutil.copyfile(ROOT / 'bazel' / name, output / name)
    (output / 'MODULE.bazel').write_text('module(name="msbuild_graph")\nlocal_dotnet_sdk = use_repo_rule("//:msbuild.bzl", "local_dotnet_sdk")\n' + f'local_dotnet_sdk(name="dotnet", path={json.dumps(str(DOTNET_ROOT))})\n')
    (output / 'host-identity.json').write_text(json.dumps({'platform': platform.platform(), 'machine': platform.machine(), 'dotnet': str(DOTNET_ROOT), 'policyRevision': 1}))
    (output / 'restore').mkdir()
    settings = dict(plugin='ReplayPlugin.dll', build_props='runner/Action.props', build_targets='runner/Action.targets', runner='runner/ActionRunner.dll', runner_support=['runner/ActionRunner.deps.json', 'runner/ActionRunner.runtimeconfig.json'], sdk='@dotnet//:files', dotnet='@dotnet//:sdk/dotnet', host_identity='host-identity.json')
    build = 'load(":graph.bzl", "graph_project")\n'
    for identity, node in sorted(nodes.items()):
        sources = set()
        restore = []
        for reachable in sorted(closures[identity]):
            dependency = nodes[reachable]
            for item in dependency['inputs']:
                if item['path'].startswith('workspace/') and item['kind'] not in ('restore', 'package'):
                    # Dependency evaluation needs projects, imports and explicitly declared
                    # evaluation extras (for example an Exists condition), never its sources.
                    if reachable == identity or item['kind'] in ('project', 'import', 'extra'):
                        source = relative(item['path'])
                        if '/obj/' not in source:
                            sources.add(source)
            project_directory = Path(relative(dependency['project'])).parent
            state = {}
            for source in sorted((workspace / project_directory / 'obj').iterdir()):
                if source.is_file() and (source.name.endswith(('.json', '.props', '.targets')) or source.name == 'project.nuget.cache'):
                    contents = source.read_text()
                    if source.name == 'project.nuget.cache':
                        cache = json.loads(contents)
                        if 'dgSpecHash' in cache:
                            cache['dgSpecHash'] = '$NORMALIZED'
                        contents = json.dumps(cache, sort_keys=True)
                    state[source.relative_to(workspace).as_posix()] = contents.replace(str(workspace), '${WORKSPACE}').replace(str(DOTNET_ROOT), '${SDK}')
            path = f'restore/{reachable}.json'
            (output / path).write_text(json.dumps(state, sort_keys=True))
            restore.append(path)
        for name in ('global.json', 'NuGet.Config', 'Directory.Build.props', 'Directory.Build.targets'):
            if (workspace / name).is_file(): sources.add(name)
        for source in sources:
            target = output / 'src' / source
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(workspace / source, target)
        package_manifest, packages = graph_packages.stage(workspace, relative(node['project']), output, identity)
        attrs = dict(settings, global_properties=node['globalProperties'], packages=packages, package_manifest=package_manifest, name='node_' + identity, project=relative(node['project']), srcs=sorted('src/' + s for s in sources), restore=restore, dependencies=[':node_' + d for d in node['dependencies']])
        build += 'graph_project(\n' + ''.join(f'    {k} = {json.dumps(v)},\n' for k, v in attrs.items()) + ')\n'
    build += 'filegroup(name="all", srcs=' + json.dumps([':node_' + n for n in graph['entryPoints']]) + ')\n'
    (output / 'BUILD.bazel').write_text(build)
    (output / 'graph.json').write_text(json.dumps(graph, indent=2))
    return graph

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for option in ('workspace', 'manifest', 'output'):
        parser.add_argument('--' + option, required=True, type=Path)
    args = parser.parse_args()
    prepare(args.workspace, args.manifest, args.output)
