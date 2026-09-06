#!/usr/bin/env python3
"""Materialize the supported local graph slice as Bazel configured project actions."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = Path(os.environ.get('SPIKE_DOTNET_ROOT', ROOT / '.tools/dotnet')).resolve()


def relative(value):
    if not value.startswith('workspace/'):
        raise ValueError('expected workspace path: ' + value)
    result = value.removeprefix('workspace/')
    if not result or Path(result).is_absolute() or '..' in Path(result).parts:
        raise ValueError('unsafe workspace path: ' + value)
    return result


def prepare(workspace, manifest, output):
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
        if node['globalProperties'] != {'configuration': 'Release'} or node['targetFramework'] != 'net10.0':
            raise ValueError('unsupported graph execution configuration')
        project = relative(node['project'])
        expected = str(Path(project).parent / 'bin/Release/net10.0' / (Path(project).stem + '.dll'))
        if node['outputs'] != [{'kind': 'assembly', 'path': 'workspace/' + expected}]:
            raise ValueError('unsupported graph output layout')
        if any(dep not in nodes for dep in node['dependencies']):
            raise ValueError('missing dependency node')
        assets = json.loads((workspace / Path(project).parent / 'obj/project.assets.json').read_text())
        if any(v['type'] == 'package' for v in assets['libraries'].values()):
            raise ValueError('package graph execution is not supported by this slice')
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
            raise ValueError('missing or escaping input: ' + item['path'])
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
            raise ValueError('stale graph input: ' + item['path'])
    output.mkdir(parents=True, exist_ok=False)
    for name in ('ReplayPlugin', 'ActionRunner'):
        result = subprocess.run([str(DOTNET_ROOT / 'dotnet'), 'build', str(ROOT / 'tools' / name), '-c', 'Release', '--nologo'], cwd=ROOT, text=True, capture_output=True)
        (output / (name + '-build.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(name + ' build failed: ' + result.stdout + result.stderr)
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
    targets.write_text(targets.read_text().replace('</Project>', '<Target Name="GraphCompileEvidence" BeforeTargets="CoreCompile"><Message Importance="high" Text="SPIKE_COMPILE:$(MSBuildProjectName)" /></Target></Project>'))
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
                if item['path'].startswith('workspace/') and item['kind'] != 'restore':
                    # Dependency evaluation needs projects and imports, never its sources.
                    if reachable == identity or item['kind'] in ('project', 'import'):
                        source = relative(item['path'])
                        if '/obj/' not in source:
                            sources.add(source)
            project_directory = Path(relative(dependency['project'])).parent
            state = {}
            for source in sorted((workspace / project_directory / 'obj').iterdir()):
                if source.is_file() and (source.name.endswith(('.json', '.props', '.targets')) or source.name == 'project.nuget.cache'):
                    state[source.relative_to(workspace).as_posix()] = source.read_text().replace(str(workspace), '${WORKSPACE}').replace(str(DOTNET_ROOT), '${SDK}')
            path = f'restore/{reachable}.json'
            (output / path).write_text(json.dumps(state, sort_keys=True))
            restore.append(path)
        for name in ('global.json', 'NuGet.Config', 'Directory.Build.props', 'Directory.Build.targets'):
            if (workspace / name).is_file(): sources.add(name)
        for source in sources:
            target = output / 'src' / source
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(workspace / source, target)
        attrs = dict(settings, name='node_' + identity, project=relative(node['project']), srcs=sorted('src/' + s for s in sources), restore=restore, dependencies=[':node_' + d for d in node['dependencies']])
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
