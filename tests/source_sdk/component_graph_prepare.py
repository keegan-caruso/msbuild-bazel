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

SDK_ARCHIVE = 'artifacts/assets/Release/Sdk/10.0.100-rtm.25523.111/dotnet-sdk-10.0.100-ubuntu.22.04-arm64.tar.gz'


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
    sdk_patch = 'patch -p1 < .qualification/sdk-redist-razor-reference.patch\n' if component == 'sdk' else ''
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
{sdk_patch}./build.sh -sb --projects /source/eng/tools/tasks/Microsoft.DotNet.UnifiedBuild.Tasks/Microsoft.DotNet.UnifiedBuild.Tasks.csproj {common} > utility-build.log 2>&1 || {{ tail -100 utility-build.log; exit 1; }}
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
    parser.add_argument('--refresh-source', action='append', default=[], help='Explicitly regenerate this existing component source archive')
    parser.add_argument('--sdk-consumer', action='store_true', help='Register the complete component-produced SDK for an app test')
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
        if set(args.refresh_source) - existing:
            raise ValueError('Can only refresh an existing component source archive')
        all_nodes = selected_nodes(graph, 'sdk', pin['sourceRevision'])
        if not existing <= all_nodes.keys():
            raise ValueError('Existing workspace contains an unknown component')
        required = set(nodes) | existing
        nodes = {name: dependencies for name, dependencies in all_nodes.items() if name in required}
    else:
        if args.refresh_source:
            raise ValueError('Source refresh requires --extend')
        work.mkdir(parents=True, exist_ok=False)
        (work / 'evaluated-graph.json').write_text(json.dumps(graph, indent=2) + '\n')
        os.link(args.native_tools.resolve(), work / 'native.tar')
        for name in ['bootstrap.tar', 'bwrap', 'Driver.csproj']:
            os.link(root / name, work / name)
    if args.sdk_consumer and 'sdk' not in nodes:
        raise ValueError('SDK consumer requires the complete SDK component graph')
    module = (root / 'MODULE.bazel').read_text()
    module = '\n'.join(line for line in module.splitlines() if 'register_toolchains(' not in line)
    controller_module = module + '\nregister_toolchains("@controller//:all")\n'
    module += ('\nregister_toolchains("//:produced_registered", "//:produced_runtime_registered")\n'
               if args.sdk_consumer else '\nregister_toolchains("@controller//:all")\n')
    fixed_inputs = {"Driver.cs": (here.parents[1] / 'tests/runtime/NativeBuild.cs.txt').read_bytes(),
                    "source_action.bzl": (here / 'source_action.bzl').read_bytes(),
                    "component_action.bzl": (here / 'component_action.bzl').read_bytes(),
                    "MODULE.bazel": module.encode()}
    if args.sdk_consumer:
        fixed_inputs['SdkDriver.cs'] = (here / 'SdkNativeBuild.cs.txt').read_bytes()
    for name, data in fixed_inputs.items():
        path = work / name
        if args.extend:
            old = path.read_bytes() if path.exists() else None
            if old != data:
                allowed_module = name == 'MODULE.bazel' and old == controller_module.encode()
                allowed_refresh = name in ('Driver.cs', 'SdkDriver.cs', 'component_action.bzl') and args.sdk_consumer and args.refresh_output_contracts
                if not (allowed_refresh or (args.sdk_consumer and args.refresh_output_contracts and allowed_module)):
                    raise ValueError('Existing workspace has a different input: ' + name)
                path.write_bytes(data)
        else:
            path.write_bytes(data)
    helpers = [here / name for name in ['component_outputs.py', 'inventory.py', 'source_action_prepare.py']]
    source_symbols = '"native_driver"'
    component_symbols = '"source_component", "component_package", "sdk_component_layout"' if args.sdk_consumer else '"source_component", "component_package"'
    build = ['load(":source_action.bzl", %s)' % source_symbols, 'load(":component_action.bzl", %s)' % component_symbols,
             'load("@rules_msbuild//msbuild:defs.bzl", "msbuild_generated_nuget_package", "msbuild_package_lock", "msbuild_graph", "msbuild_graph_runner", "msbuild_graph_test")']
    if args.sdk_consumer:
        build.append('load("@rules_msbuild//msbuild:sdk.bzl", "msbuild_sdk")')
    build.append('native_driver(name="driver",driver_sdk="@controller//:sdk_host",driver_project="Driver.csproj",driver_source="Driver.cs")')
    if args.sdk_consumer:
        build.append('native_driver(name="sdk_driver",driver_sdk="@controller//:sdk_host",driver_project="Driver.csproj",driver_source="SdkDriver.cs")')
    for name, dependencies in nodes.items():
        source = work / (name + '.tar')
        command = work / (name + '.sh')
        built_sdks = [item['Identity'] for item in graph['nodes'][name]['Items']['BuiltSdkPackage']]
        build_script = script(name, dependencies, built_sdks)
        selected_helpers = helpers + ([here / 'patches/sdk-redist-razor-reference.patch'] if name == 'sdk' else [])
        if name in existing:
            if not source.is_file():
                raise ValueError('Existing component input differs from evaluated graph: ' + name)
            if name in args.refresh_source:
                replacement = source.with_suffix('.tar.new')
                try:
                    select(root / 'sources.tar', name, replacement, selected_helpers)
                    replacement.replace(source)
                finally:
                    replacement.unlink(missing_ok=True)
            if command.read_text() != build_script:
                if not args.refresh_output_contracts:
                    raise ValueError('Existing component script differs from evaluated graph: ' + name)
                command.write_text(build_script)
        else:
            select(root / 'sources.tar', name, source, selected_helpers)
            command.write_text(build_script)
        sdk_archive = ',sdk_archive=' + json.dumps(SDK_ARCHIVE) if name == 'sdk' and args.sdk_consumer else ''
        driver = ':sdk_driver' if name == 'sdk' and args.sdk_consumer else ':driver'
        build.append('source_component(name=%s,driver=%s,sources=%s,script=%s,deps=%s,native_tools="native.tar",bootstrap="bootstrap.tar",sandbox="bwrap"%s,exec_compatible_with=["@platforms//os:linux","@platforms//cpu:aarch64"])' %
                     (json.dumps(name), json.dumps(driver), json.dumps(name + '.tar'), json.dumps(name + '.sh'), json.dumps([':' + item for item in dependencies]), sdk_archive))
    build.append('filegroup(name="components",srcs=%s)' % json.dumps([':' + name for name in nodes]))
    if args.sdk_consumer:
        build.extend([
            'sdk_component_layout(name="layout",component=":sdk")',
            'filegroup(name="dotnet",srcs=[":layout"],output_group="dotnet")',
            'msbuild_sdk(name="produced",dotnet=":dotnet",files=[":layout"],sdk_version="10.0.100",runtime_version="10.0.0",runtime_identifier="linux-arm64")',
            'msbuild_graph_runner(name="sdk_runner")',
            'msbuild_graph(name="sdk_graph",runner=":sdk_runner",contract="sdk-contract.json",srcs=["SdkLib.csproj","SdkLib.cs","SdkSmoke.csproj","SdkSmoke.cs"],project_outputs={"SdkSmoke.csproj|net10.0":["bin/Release/net10.0","SdkSmoke.dll","Exe"]})',
            'msbuild_graph_test(name="smoke",graph=":sdk_graph",project="SdkSmoke.csproj")',
        ])
        consumer_files = {
            'SdkLib.csproj': '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup><ItemGroup><Compile Include="SdkLib.cs" /></ItemGroup></Project>\n',
            'SdkLib.cs': 'public static class SdkLib { public static int Value() => 1; }\n',
            'SdkSmoke.csproj': '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><UseAppHost>false</UseAppHost><EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup><ItemGroup><Compile Include="SdkSmoke.cs" /><ProjectReference Include="SdkLib.csproj" /></ItemGroup></Project>\n',
            'SdkSmoke.cs': 'System.Console.WriteLine("SDK_FROM_COMPONENTS="+System.Environment.Version); return System.Environment.Version.ToString()=="10.0.0" && SdkLib.Value()==1 ? 0 : 1;\n',
        }
        consumer_files['sdk-contract.json'] = json.dumps(dict(Version=1, Entry='SdkSmoke.csproj', SdkVersion='10.0.100', Properties={'Configuration':'Release'}, SharedInputs=[], Projects={
            project: dict(Inputs=[project, source], OutputDirectories=[f'bin/{project[:-7]}/Release/net10.0', f'obj/{project[:-7]}/Release/net10.0']) for project, source in [('SdkLib.csproj','SdkLib.cs'),('SdkSmoke.csproj','SdkSmoke.cs')]}), indent=2)+'\n'
        # Projects share a source directory; authored output paths remain distinct.
        for name in ['SdkLib.csproj', 'SdkSmoke.csproj']:
            stem = name[:-7]
            consumer_files[name] = consumer_files[name].replace('<PropertyGroup>', '<PropertyGroup><BaseOutputPath>bin/'+stem+'/</BaseOutputPath><BaseIntermediateOutputPath>obj/'+stem+'/</BaseIntermediateOutputPath>')
        build[-2] = build[-2].replace('bin/Release/net10.0', 'bin/SdkSmoke/Release/net10.0')
        present = [name for name in consumer_files if (work / name).exists()]
        if present and len(present) != len(consumer_files):
            missing = [name for name in consumer_files if name not in present]
            raise ValueError('Existing SDK consumer fixture is incomplete; missing: ' + ', '.join(missing))
        if not present:
            for name, contents in consumer_files.items():
                (work / name).write_text(contents)
    if 'command-line-api' in nodes:
        build.extend([
            'component_package(name="commandline_archive",component=":command-line-api",member="artifacts/packages/Release/Shipping/command-line-api/System.CommandLine.2.0.0.nupkg")',
            'msbuild_generated_nuget_package(name="package",package_id="System.CommandLine",version="2.0.0",archive=":commandline_archive")',
            'msbuild_package_lock(name="lock",packages=[":package"])',
            'msbuild_graph_runner(name="consumer_runner")',
            'msbuild_graph(name="consumer_graph",runner=":consumer_runner",contract="consumer-contract.json",srcs=["App.csproj","App.cs"],package_lock=":lock",project_outputs={"App.csproj|net10.0":["bin/App/Release/net10.0","App.dll","Exe"]})',
            'msbuild_graph_test(name="consumer",graph=":consumer_graph",project="App.csproj")',
        ])
        if not (work / 'App.csproj').exists():
            (work / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><UseAppHost>false</UseAppHost><EnableDefaultCompileItems>false</EnableDefaultCompileItems><BaseOutputPath>bin/App/</BaseOutputPath><BaseIntermediateOutputPath>obj/App/</BaseIntermediateOutputPath></PropertyGroup><ItemGroup><Compile Include="App.cs" /><PackageReference Include="System.CommandLine" Version="2.0.0" /></ItemGroup></Project>')
            (work / 'App.cs').write_text('var command = new System.CommandLine.RootCommand("qualification"); System.Console.WriteLine(command.Options.Count); return command.Options.Count == 2 ? 0 : 1;')
        (work / 'consumer-contract.json').write_text(json.dumps(dict(Version=1,Entry='App.csproj',SdkVersion='10.0.100' if args.sdk_consumer else '10.0.400',Properties={'Configuration':'Release'},SharedInputs=[],Projects={'App.csproj':dict(Inputs=['App.csproj','App.cs'],OutputDirectories=['bin/App/Release/net10.0','obj/App/Release/net10.0'])})))
    build_file = work / 'BUILD.bazel'
    if not args.extend or build_file.read_text() != '\n'.join(build) + '\n':
        build_file.write_text('\n'.join(build) + '\n')
    if args.extend and previous_graph != graph:
        (work / 'evaluated-graph.json').write_text(json.dumps(graph, indent=2) + '\n')
    print(work, flush=True)


if __name__ == '__main__':
    main()
