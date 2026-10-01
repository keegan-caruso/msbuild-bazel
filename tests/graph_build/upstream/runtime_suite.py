"""Declare reviewed upstream VSTest suites on a graph-built source host."""
import argparse
import ast
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workspace', type=Path, help='combined source app/host and Pipelines graph')
    parser.add_argument('vstest', type=Path)
    parser.add_argument('--slice', action='append', choices=['pipelines', 'collections', 'threading', 'filesystem', 'sockets'], help='repeat reviewed suite selections; default Pipelines')
    args = parser.parse_args()
    root = args.workspace.resolve()
    manifest = json.loads((root / 'application.json').read_text())
    assert manifest['framework'] == '10.0.0'
    selection = json.loads((ROOT / 'tests/explicit_msbuild/runtime/subset_slices.json').read_text())
    assert selection['commit'] == manifest['commit']
    slices = args.slice or ['pipelines']
    assert len(slices) == len(set(slices)), 'Duplicate suite selections'
    tree = ast.parse((root / 'graph.generated.bzl').read_text())
    values = [ast.literal_eval(keyword.value) for node in ast.walk(tree) if isinstance(node, ast.Call)
              for keyword in node.keywords if keyword.arg == 'project_outputs']
    assert len(values) == 1
    tests = []
    for name in slices:
        reviewed = next(row for row in selection['slices'] if row['name'] == name)
        for entry in reviewed['entries']:
            project = entry if isinstance(entry, str) else entry['project']
            framework = reviewed['framework'] if isinstance(entry, str) else entry['framework']
            if '/tests/' not in project:
                continue
            key = project + '|' + framework
            assert key in values[0], 'Missing reviewed suite configuration: ' + key
            directory, assembly, kind = values[0][key]
            assert kind in ['Exe', 'Library']
            label = 'pipelines_suite' if name == 'pipelines' else Path(project).stem.lower().replace('.', '_') + '_suite'
            tests.append(dict(project=project, framework=framework, directory=directory, assembly=assembly,
                target='//:' + label, filter=reviewed.get('filters', {}).get(project)))
    assert tests and len({test['target'] for test in tests}) == len(tests)
    data = args.vstest.read_bytes()
    assert hashlib.sha256(data).hexdigest() == '3aabba2641a165f8274fbad94ed1c4e2a004877d37b2ddfab89962487f3dceab'
    runner = root / 'suite-runner'
    runner.mkdir(exist_ok=False)
    shutil.copyfile(args.vstest, runner / 'vstest.nupkg')
    adapters = list((root / '.package-source').glob('xunit.runner.visualstudio.*.nupkg'))
    assert len(adapters) == 1
    adapter = adapters[0]
    with zipfile.ZipFile(adapter) as archive:
        paths = {str(Path(name).parent) for name in archive.namelist()
                 if name.endswith('xunit.runner.visualstudio.testadapter.dll') and '/net4' not in name}
    assert len(paths) == 1
    version = adapter.name.removeprefix('xunit.runner.visualstudio.').removesuffix('.nupkg')
    def package(name, identity, version, path):
        payload = (root / path).read_bytes()
        return 'msbuild_nuget_package(' + ','.join(key + '=' + json.dumps(value) for key, value in dict(
            name=name, package_id=identity, version=version, archive=str(path),
            archive_sha256=hashlib.sha256(payload).hexdigest(),
            content_hash=base64.b64encode(hashlib.sha512(payload).digest()).decode()).items()) + ')'
    probe = root / 'suite-probe'
    probe.mkdir(exist_ok=False)
    shutil.copyfile(ROOT / 'tests/explicit_msbuild/runtime/SubsetProbe.cs.txt', probe / 'StartupHook.cs')
    (probe / 'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><Nullable>enable</Nullable></PropertyGroup></Project>')
    (probe / 'contract.json').write_text(json.dumps(dict(Version=1, Entry='Probe.csproj', SdkVersion='10.0.400',
        Properties=dict(Configuration='Release'), SharedInputs=[], Projects={'Probe.csproj': dict(
            Inputs=['Probe.csproj', 'StartupHook.cs'], OutputDirectories=['bin/Release/net10.0', 'obj/Release/net10.0'])}), indent=2) + '\n')
    host = root / 'suite-host'
    host.mkdir(exist_ok=False)
    inventory = {name: [] for framework in (Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']) / 'shared/Microsoft.NETCore.App').iterdir()
                 if framework.is_dir() for name in [path.name for path in framework.iterdir() if path.suffix in ['.dll', '.so']]}
    shared = 'shared/Microsoft.NETCore.App/10.0.0'
    inventory.update({name: [shared + '/' + name] for name in manifest['managed']})
    inventory.update({name: [producer['path']] for name, producer in manifest['native'].items()})
    for name in manifest.get('private', {}):
        inventory.setdefault(name, []).append('private/' + name)
    (host / 'runtime-inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
    (host / 'host.sh').write_text('''#!/bin/sh
set -eu
ulimit -c 0
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export DOTNET_ROOT="$root"
export DOTNET_ReadyToRun=0
export DOTNET_STARTUP_HOOKS="$root/probe/Probe.dll"
export QUALIFICATION_HOST_ROOT="$root"
exec "$root/dotnet" "$@"
''')
    (host / 'host.sh').chmod(0o755)
    lines = ['load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package","msbuild_test_tool","msbuild_graph","msbuild_graph_layout","msbuild_layout","msbuild_runtime","msbuild_graph_test")',
        package('suite_runner_archive', 'Microsoft.TestPlatform.CLI', '17.14.1', Path('suite-runner/vstest.nupkg')),
        package('suite_adapter_archive', 'xunit.runner.visualstudio', version, adapter.relative_to(root)),
        'msbuild_test_tool(name="suite_runner",package=":suite_runner_archive",path="contentFiles/any/net9.0/vstest.console.dll")',
        'msbuild_test_tool(name="suite_adapter",package=":suite_adapter_archive",path=' + json.dumps(next(iter(paths))) + ')',
        'msbuild_graph(name="suite_probe",runner=":graph_runner",contract="suite-probe/contract.json",source_root="suite-probe",srcs=["suite-probe/Probe.csproj","suite-probe/StartupHook.cs"],linux_stable_paths=True,linux_worker=True,project_outputs={"Probe.csproj|net10.0":["bin/Release/net10.0","Probe.dll","Library"]})',
        'msbuild_graph_layout(name="suite_probe_layout",graph=":suite_probe",project="Probe.csproj",framework="net10.0")',
        'msbuild_layout(name="suite_source_runtime",paths={":app_source_runtime":".",":suite_probe_layout":"probe","suite-host/host.sh":"host.sh","suite-host/runtime-inventory.json":"runtime-inventory.json"})',
        'msbuild_runtime(name="suite_host",layout=":suite_source_runtime",entry_point="host.sh",runtime_identifier="linux-arm64",version="10.0.0")']
    if any(test['filter'] for test in tests):
        settings_tool = root / 'suite-settings-tool'
        settings_tool.mkdir(exist_ok=False)
        shutil.copyfile(Path(__file__).with_name('RuntimeTestSettings.cs.txt'), settings_tool / 'Program.cs')
        shutil.copyfile(Path(__file__).with_name('runtime_test_settings.bzl'), root / 'runtime_test_settings.bzl')
        (settings_tool / 'Settings.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
        (settings_tool / 'contract.json').write_text(json.dumps(dict(Version=1, Entry='Settings.csproj', SdkVersion='10.0.400',
            Properties=dict(Configuration='Release'), SharedInputs=[], Projects={'Settings.csproj': dict(Inputs=['Settings.csproj', 'Program.cs'],
            OutputDirectories=['bin/Release/net10.0', 'obj/Release/net10.0'])}), indent=2) + '\n')
        lines += ['load(":runtime_test_settings.bzl","runtime_test_settings")',
            'msbuild_graph(name="suite_settings_tool",runner=":graph_runner",contract="suite-settings-tool/contract.json",source_root="suite-settings-tool",srcs=["suite-settings-tool/Settings.csproj","suite-settings-tool/Program.cs"],linux_stable_paths=True,linux_worker=True,project_outputs={"Settings.csproj|net10.0":["bin/Release/net10.0","Settings.dll","Exe"]})',
            'msbuild_graph_layout(name="suite_settings_tool_layout",graph=":suite_settings_tool",project="Settings.csproj",framework="net10.0")']
    for test in tests:
        label = test['target'].removeprefix('//:')
        attributes = dict(name=label, graph=':graph', project=test['project'], framework=test['framework'],
            runtime_host=':suite_host', test_protocol='vstest', test_runner=':suite_runner', test_adapters=[':suite_adapter'], size='large')
        if test['filter']:
            layout, settings = label + '_layout', label + '_settings'
            lines += ['msbuild_graph_layout(name=' + json.dumps(layout) + ',graph=":graph",project=' + json.dumps(test['project']) + ',framework=' + json.dumps(test['framework']) + ')',
                'runtime_test_settings(name=' + json.dumps(settings) + ',tool=":suite_settings_tool_layout",layout=' + json.dumps(':' + layout) + ',filter=' + json.dumps(test['filter']) + ')']
            attributes['test_settings'] = ':' + settings
            test['settings'] = settings + '.runsettings'
        else:
            attributes['test_settings_output'] = '.runsettings'
        lines.append('msbuild_graph_test(' + ','.join(key + '=' + json.dumps(value) for key, value in attributes.items()) + ')')
    lines.append('test_suite(name="runtime_suites",tests=' + json.dumps([test['target'] for test in tests]) + ')')
    with (root / 'BUILD.bazel').open('a') as build:
        build.write('\n' + '\n'.join(lines) + '\n')
    (root / 'suite.json').write_text(json.dumps(dict(tests[0], tests=tests, host='suite_source_runtime.layout', inventory=inventory), indent=2) + '\n')
    print(root, flush=True)


if __name__ == '__main__':
    main()
