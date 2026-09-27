"""Capture MSBuild's configured VMR repository graph for qualification.

This evaluates pinned upstream projects. It does not execute their targets or
produce a hermetic Bazel graph: target-time package and asset discovery remains
part of the component handoff work.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess

from inventory import inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--shared-components', choices=['true', 'false'], default='true')
    parser.add_argument('--build-pass', choices=['1', '2'])
    args = parser.parse_args()
    source = args.source.resolve()
    pin = json.loads(Path(__file__).with_name('pin.json').read_text())
    definitions = inventory(source, pin)
    properties = {
        'DotNetBuildSourceOnly': 'true',
        'DotNetBuildSharedComponents': args.shared_components,
        'TargetArchitecture': pin['configuration']['architecture'],
        'Configuration': pin['configuration']['configuration'],
        'OfficialBuildId': pin['releaseManifest']['officialBuildId'],
    }
    if args.build_pass:
        properties['DotNetBuildPass'] = args.build_pass
    environment = dict(os.environ, DOTNET_PROCESSOR_COUNT='2',
                       DOTNET_CLI_TELEMETRY_OPTOUT='1', NUGET_PACKAGES=str(source / '.packages'))
    nodes = {}
    for repository in definitions['repositories']:
        name = repository['path']
        command = [str(source / '.dotnet/dotnet'), 'msbuild', 'repo-projects/' + name + '.proj', '-nologo',
                   *('/p:' + key + '=' + value for key, value in properties.items()),
                   '/getItem:RepositoryReference,ProjectReference,EnvironmentVariables,BuiltSdkPackage',
                   '/getProperty:TargetRid,DotNetBuildSharedComponents,DotNetBuildPass,BuildScript,BuildArgs,CommonArgs']
        result = subprocess.run(command, cwd=source, env=environment, capture_output=True, text=True, timeout=120)
        if result.returncode:
            raise RuntimeError(name + ':\n' + result.stdout + result.stderr)
        nodes[name] = json.loads(result.stdout)
    # Keep complete metadata in nodes, including references excluded from a pass.
    # This order covers only the repositories that the selected SDK build enables.
    order, visiting, visited = [], set(), set()

    def visit(name):
        if name in visiting:
            raise ValueError('Cycle in evaluated repository graph: ' + name)
        if name in visited:
            return
        visiting.add(name)
        for reference in nodes[name]['Items']['RepositoryReference']:
            if reference.get('BuildReference', 'true').lower() != 'false':
                visit(reference['Identity'])
        visiting.remove(name)
        visited.add(name)
        order.append(name)

    visit('sdk')
    report = {'schemaVersion': 1, 'sourceRevision': pin['sourceRevision'],
              'globalProperties': properties, 'sdkDependencyOrder': order, 'nodes': nodes,
              'status': 'evaluated repository references; target-time outputs and hermetic closure not qualified'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print('SDK component order:', ', '.join(order))


if __name__ == '__main__':
    main()
