"""Prepare a configured SDK component closure for qualification.

Each source archive contains its own implementation, shared Arcade scripts, and
VMR/project metadata. MSBuild's evaluated repository graph supplies the edges.
"""
import argparse
import json
import os
from pathlib import Path
import re
import tarfile

from component_sources import select
from inventory import digest


def selected_nodes(graph, through, revision):
    if graph['sourceRevision'] != revision:
        raise ValueError('Evaluated graph source revision differs from the pinned archive')
    properties = graph['globalProperties']
    if properties.get('DotNetBuildSourceOnly') != 'true' or properties.get('DotNetBuildSharedComponents') != 'true':
        raise ValueError('Expected the configured source-only shared-component graph')
    if properties.get('Configuration') != 'Release' or properties.get('TargetArchitecture') != 'arm64':
        raise ValueError('Expected the qualified Release/arm64 configuration')
    if properties.get('DotNetBuildPass') not in (None, ''):
        raise ValueError('Expected the complete SDK graph, not one build pass')
    order = graph['sdkDependencyOrder']
    if through not in order or len(set(order)) != len(order):
        raise ValueError('Missing target or duplicate component in evaluated order: ' + through)
    dependencies_by_name = {}
    for name in order:
        items = graph['nodes'][name]['Items']
        if 'BuiltSdkPackage' not in items:
            raise ValueError('Evaluated graph lacks built SDK package declarations: ' + name)
        dependencies = [item['Identity'] for item in items['RepositoryReference']
                        if item.get('BuildReference', 'true').lower() != 'false']
        if any(dependency not in dependencies_by_name for dependency in dependencies):
            raise ValueError('Evaluated dependency is missing or out of order: ' + name)
        dependencies_by_name[name] = dependencies
    required = set()

    def visit(name):
        if name in required:
            return
        required.add(name)
        for dependency in dependencies_by_name[name]:
            visit(dependency)

    visit(through)
    return {name: dependencies_by_name[name] for name in order if name in required}


def validate_native_archive(path):
    with tarfile.open(path) as native:
        if any(item.name == 'etc/ssl/private' or item.name.startswith('etc/ssl/private/') for item in native):
            raise ValueError('Native tool archive includes private host material')


def same_input(first, second):
    return os.path.samefile(first, second) or digest(first) == digest(second)


def expanded_sdk_graph(previous, current):
    stripped = json.loads(json.dumps(current))
    for node in stripped['nodes'].values():
        node['Items'].pop('BuiltSdkPackage', None)
    return previous == stripped


def script(component, dependencies, built_sdks):
    projects = ';'.join('/source/repo-projects/' + name + '.proj' for name in dependencies)
    common = '--configuration Release --arch arm64 --official-build-id 20251023.11 --branding rtm /p:Publish=false --source-repository https://github.com/dotnet/dotnet --source-version b0f34d51fccc69fd334253924abd8d6853fad7aa'
    extraction = ''
    if dependencies:
        extraction = f'''cat > extract-dependency-tools.proj <<'XML'
<Project>
  <Target Name="Restore"><MSBuild Projects="{projects}" Targets="Restore" Properties="BuildProjectReferences=false" BuildInParallel="false" /></Target>
  <Target Name="Build"><MSBuild Projects="{projects}" Targets="ExtractToolPackage" Properties="BuildProjectReferences=false" BuildInParallel="false" /></Target>
</Project>
XML
./build.sh -sb --projects /source/extract-dependency-tools.proj {common} > dependency-tools.log 2>&1 || {{ tail -100 dependency-tools.log; exit 1; }}
'''
    patch = 'patch -p1 < identitymodel.patch' if component == 'source-build-reference-packages' else ''
    if any(not re.fullmatch(r'[A-Za-z0-9_.-]+', sdk) for sdk in built_sdks):
        raise ValueError('Invalid built SDK package identity: ' + component)
    extra_trees = ['artifacts/source-built-sdks/' + sdk for sdk in built_sdks]
    if component == 'source-build-reference-packages':
        extra_trees.append('prereqs/packages/reference')
    extra = ' '.join('--extra-tree ' + path for path in extra_trees)
    # FSharp's local-build Xliff update calls UpdateXlf in an inner
    # netstandard2.1 build where the target is absent. Its upstream --ci mode
    # disables only that local translation-file update for this release build.
    component_mode = '--ci ' if component == 'fsharp' else ''
    return f'''set -euo pipefail
export DOTNET_PROCESSOR_COUNT=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_GENERATE_ASPNET_CERTIFICATE=false NuGetAudit=false
{patch}
./prep-source-build.sh --no-sdk --no-bootstrap --no-artifacts --no-prebuilts > preparation.log 2>&1 || {{ tail -100 preparation.log; exit 1; }}
if [ -d /tmp/component-inputs ]; then cp -a /tmp/component-inputs/. /source/; fi
./build.sh -sb --projects /source/eng/tools/tasks/Microsoft.DotNet.UnifiedBuild.Tasks/Microsoft.DotNet.UnifiedBuild.Tasks.csproj {common} > utility-build.log 2>&1 || {{ tail -100 utility-build.log; exit 1; }}
{extraction}
/usr/bin/time -v -o build.time ./build.sh -sb {component_mode}--projects /source/repo-projects/{component}.proj {common} /p:BuildProjectReferences=false /p:BuildInParallel=false > build.log 2>&1 || {{ tail -120 build.log; exit 1; }}
mkdir result
python3 .qualification/component_outputs.py /source {component} result/component.tar {extra}
tar -cf result.tar *.log build.time result/component.json artifacts/log artifacts/obj/manifests/Release/{component}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_action', type=Path)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--graph', type=Path, required=True, help='Output of evaluate_graph.py for the pinned Release/arm64 source build')
    parser.add_argument('--native-tools', type=Path, required=True, help='Reviewed native tool archive; excludes private host material')
    parser.add_argument('--through', default='command-line-api', help='Selected component and its evaluated dependency closure')
    parser.add_argument('--extend', action='store_true', help='Add a component closure to an existing generated workspace')
    parser.add_argument('--refresh-output-contracts', action='store_true', help='Accept newly evaluated built SDK items and refresh component scripts')
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    root, work = args.source_action.resolve(), args.directory.resolve()
    pin = json.loads((here / 'pin.json').read_text())
    graph = json.loads(args.graph.read_text())
    nodes = selected_nodes(graph, args.through, pin['sourceRevision'])
    validate_native_archive(args.native_tools)
    existing = set()
    if args.extend:
        if not work.is_dir():
            raise ValueError('Existing workspace is missing')
        previous_graph = json.loads((work / 'evaluated-graph.json').read_text())
        if previous_graph != graph and not (args.refresh_output_contracts and expanded_sdk_graph(previous_graph, graph)):
            raise ValueError('Existing workspace has a different evaluated graph')
        if not same_input(work / 'native.tar', args.native_tools):
            raise ValueError('Existing workspace has a different native archive')
        for name in ['bootstrap.tar', 'bwrap', 'Driver.csproj']:
            if not same_input(work / name, root / name):
                raise ValueError('Existing workspace has a different input: ' + name)
        existing = {path.stem for path in work.glob('*.sh')}
        all_nodes = selected_nodes(graph, 'sdk', pin['sourceRevision'])
        if not existing <= all_nodes.keys():
            raise ValueError('Existing workspace contains an unknown component')
        required = set(nodes) | existing
        nodes = {name: dependencies for name, dependencies in all_nodes.items() if name in required}
    else:
        work.mkdir(parents=True, exist_ok=False)
        (work / 'evaluated-graph.json').write_text(json.dumps(graph, indent=2) + '\n')
        os.link(args.native_tools.resolve(), work / 'native.tar')
        for name in ['bootstrap.tar', 'bwrap', 'Driver.csproj']:
            os.link(root / name, work / name)
    module = (root / 'MODULE.bazel').read_text()
    module = '\n'.join(line for line in module.splitlines() if 'register_toolchains(' not in line)
    module += '\nregister_toolchains("@controller//:all")\n'
    fixed_inputs = {"Driver.cs": (here.parents[1] / 'tests/explicit_msbuild/runtime/NativeBuild.cs.txt').read_bytes(),
                    "source_action.bzl": (here / 'source_action.bzl').read_bytes(),
                    "component_action.bzl": (here / 'component_action.bzl').read_bytes(),
                    "MODULE.bazel": module.encode()}
    for name, data in fixed_inputs.items():
        path = work / name
        if args.extend:
            if path.read_bytes() != data:
                raise ValueError('Existing workspace has a different input: ' + name)
        else:
            path.write_bytes(data)
    helpers = [here / name for name in ['component_outputs.py', 'inventory.py', 'source_action_prepare.py']]
    build = ['load(":source_action.bzl", "native_driver")', 'load(":component_action.bzl", "source_component", "component_package")',
             'load("@rules_msbuild//msbuild:defs.bzl", "msbuild_generated_nuget_package", "msbuild_package_lock", "msbuild_test")',
             'native_driver(name="driver",driver_sdk="@controller//:sdk_host",driver_project="Driver.csproj",driver_source="Driver.cs")']
    for name, dependencies in nodes.items():
        source = work / (name + '.tar')
        command = work / (name + '.sh')
        built_sdks = [item['Identity'] for item in graph['nodes'][name]['Items']['BuiltSdkPackage']]
        build_script = script(name, dependencies, built_sdks)
        if name in existing:
            if not source.is_file():
                raise ValueError('Existing component input differs from evaluated graph: ' + name)
            if command.read_text() != build_script:
                if not args.refresh_output_contracts:
                    raise ValueError('Existing component script differs from evaluated graph: ' + name)
                command.write_text(build_script)
        else:
            select(root / 'sources.tar', name, source, helpers)
            command.write_text(build_script)
        build.append('source_component(name=%s,driver=":driver",sources=%s,script=%s,deps=%s,native_tools="native.tar",bootstrap="bootstrap.tar",sandbox="bwrap",exec_compatible_with=["@platforms//os:linux","@platforms//cpu:aarch64"])' %
                     (json.dumps(name), json.dumps(name + '.tar'), json.dumps(name + '.sh'), json.dumps([':' + item for item in dependencies])))
    build.append('filegroup(name="components",srcs=%s)' % json.dumps([':' + name for name in nodes]))
    if 'command-line-api' in nodes:
        build.extend([
            'component_package(name="commandline_archive",component=":command-line-api",member="artifacts/packages/Release/Shipping/command-line-api/System.CommandLine.2.0.0.nupkg")',
            'msbuild_generated_nuget_package(name="package",package_id="System.CommandLine",version="2.0.0",archive=":commandline_archive")',
            'msbuild_package_lock(name="lock",packages=[":package"])',
            'msbuild_test(name="consumer",project="App.csproj",srcs=["App.cs"],package_lock=":lock",deps=[":package"],target_framework="net10.0",use_apphost=False)',
        ])
        if not (work / 'App.csproj').exists():
            (work / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="System.CommandLine" Version="2.0.0" /></ItemGroup></Project>')
            (work / 'App.cs').write_text('var command = new System.CommandLine.RootCommand("qualification"); System.Console.WriteLine(command.Options.Count); return command.Options.Count == 2 ? 0 : 1;')
    build_file = work / 'BUILD.bazel'
    if not args.extend or build_file.read_text() != '\n'.join(build) + '\n':
        build_file.write_text('\n'.join(build) + '\n')
    if args.extend and previous_graph != graph:
        (work / 'evaluated-graph.json').write_text(json.dumps(graph, indent=2) + '\n')
    print(work, flush=True)


if __name__ == '__main__':
    main()
