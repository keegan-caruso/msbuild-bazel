#!/usr/bin/env python3
"""Ordinary SDK PrivateAssets oracle and reusable Left-only managed fixture."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from binary_inputs import Packages
from prepare_graph import DOTNET_ROOT, ROOT
sys.path.insert(0, str(ROOT / 'tests/graph'))
from test_export_graph import write_fixture

DEFAULT_PRIVATE_ASSETS = 'contentfiles;analyzers;build'


def configure(workspace, package_feed, version='1.0.0', private_assets=None):
    """Configure an existing diamond using an in-workspace feed and exact package pin."""
    workspace, package_feed = Path(workspace).resolve(), Path(package_feed).resolve()
    feed = package_feed.relative_to(workspace).as_posix()
    project = workspace / 'src/Left/Left.csproj'
    tree = ET.parse(project)
    reference = tree.getroot().find('.//PackageReference[@Include="Spike.Binary"]')
    if reference is None:
        reference = ET.SubElement(ET.SubElement(tree.getroot(), 'ItemGroup'),
                                  'PackageReference', Include='Spike.Binary')
    reference.set('Version', '[' + version + ']')
    if private_assets is None:
        reference.attrib.pop('PrivateAssets', None)
    else:
        reference.set('PrivateAssets', private_assets)
    tree.write(project)
    (project.parent / 'Value.cs').write_text('namespace Left; public static class Value { public static string Text => Shared.Message.Value + ":left/" + Spike.Binary.Value.Read().Split(\'/\')[0].Replace("binary-", "package-"); }\n')
    config = ET.parse(workspace / 'NuGet.Config')
    sources = config.getroot().find('packageSources')
    for item in list(sources):
        if item.get('key') == 'spike-local':
            sources.remove(item)
    ET.SubElement(sources, 'add', key='spike-local', value=feed)
    config.write(workspace / 'NuGet.Config')


def probe(output):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    dotnet = DOTNET_ROOT / 'dotnet'

    def run(name, command, cwd, expected_success=True):
        environment = dict(os.environ, DOTNET_CLI_HOME=str(cwd / '.dotnet-home'),
            NUGET_PACKAGES=str(cwd / '.nuget/packages'), MSBUILDDISABLENODEREUSE='1',
            DOTNET_NOLOGO='1', DOTNET_CLI_TELEMETRY_OPTOUT='1')
        result = subprocess.run([str(a) for a in command], cwd=cwd, env=environment,
            capture_output=True, text=True, timeout=180)
        log = output / (name + '.log')
        log.write_text(result.stdout + result.stderr)
        if expected_success and result.returncode:
            raise RuntimeError(name + ' failed; see ' + str(log) + '\n' + result.stdout + result.stderr)
        return result

    packages = Packages(output / 'package-build', dotnet, run)
    cases = {}
    for name, metadata in (('omitted', None), ('default', DEFAULT_PRIVATE_ASSETS), ('all', 'all'), ('none', 'none')):
        workspace = output / name
        write_fixture(workspace)
        pins = packages.feed(workspace / '.feed')
        configure(workspace, workspace / '.feed', private_assets=metadata)
        run(name + '-restore', [dotnet, 'msbuild', 'build.proj', '-t:Restore', '-p:Configuration=Release', '-nodeReuse:false', '-nologo'], workspace)
        nodes = {}
        for project in ('Shared', 'Left', 'Right', 'App'):
            directory = workspace / 'src' / project
            assets = json.loads((directory / 'obj/project.assets.json').read_text())
            target = next(iter(assets['targets'].values()))
            nodes[project] = dict(packages=sorted(k for k, v in assets['libraries'].items() if v['type'] == 'package'),
                assets={k: {kind: sorted(v.get(kind, {})) for kind in ('compile', 'runtime')} for k, v in target.items() if v['type'] == 'package'})
        run(name + '-build', [dotnet, 'msbuild', 'build.proj', '-t:Build', '-graphBuild', '-isolateProjects', '-p:Configuration=Release', '-nodeReuse:false', '-nologo'], workspace)
        for project, node in nodes.items():
            node['outputFiles'] = sorted(p.name for p in (workspace / 'src' / project / 'bin/Release/net10.0').iterdir() if p.is_file())
        app_output = workspace / 'src/App/bin/Release/net10.0'
        package_copies = {}
        for package in ('Spike.Binary', 'Spike.Leaf'):
            assembly = package + '.dll'
            installed = workspace / '.nuget/packages' / package.lower() / '1.0.0'
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            package_copies[assembly] = dict(
                outputSha256=digest(app_output / assembly) if (app_output / assembly).exists() else None,
                runtimeSha256=digest(installed / 'lib/net10.0' / assembly),
                referenceSha256=digest(installed / 'ref/net10.0' / assembly))
        isolated = output / (name + '-runtime')
        shutil.copytree(app_output, isolated)
        runtime = run(name + '-runtime', [dotnet, isolated / 'App.dll'], isolated, expected_success=False)
        # Direct App package access is a separate compiler visibility control.
        program = workspace / 'src/App/Program.cs'
        program.write_text(program.read_text() + '\nConsole.WriteLine(Spike.Binary.Value.Read());\n')
        visible = run(name + '-visibility', [dotnet, 'msbuild', 'src/App/App.csproj', '-t:Build', '-graphBuild', '-isolateProjects', '-p:Configuration=Release', '-nodeReuse:false', '-nologo'], workspace, expected_success=False)
        deps = json.loads((app_output / 'App.deps.json').read_text())
        cases[name] = dict(privateAssets=metadata, nodes=nodes, packageCopies=package_copies,
            runtimeReturncode=runtime.returncode, runtimeOutput=runtime.stdout.strip(), runtimeError=runtime.stderr,
            appDirectPackageCompileReturncode=visible.returncode,
            appDirectPackageCompileDiagnostic='CS0103' if 'CS0103' in visible.stdout + visible.stderr else None,
            appDependencyLibraries=deps['libraries'], packagePins=pins)
        (output / 'report.json').write_text(json.dumps(dict(schemaVersion=1, cases=cases), indent=2))
        print(name, json.dumps(dict(packages={p:n['packages'] for p,n in nodes.items()},
            runtimeReturncode=runtime.returncode, runtimeOutput=runtime.stdout.strip(),
            appDirectPackageCompileReturncode=visible.returncode)), flush=True)
    return dict(schemaVersion=1, cases=cases)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    probe(args.output)
