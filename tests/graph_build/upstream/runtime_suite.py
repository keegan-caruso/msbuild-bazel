"""Declare the reviewed Pipelines VSTest harness on a graph-built source host."""
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
    args = parser.parse_args()
    root = args.workspace.resolve()
    manifest = json.loads((root / 'application.json').read_text())
    assert manifest['framework'] == '10.0.0'
    project = 'src/libraries/System.IO.Pipelines/tests/System.IO.Pipelines.Tests.csproj'
    tree = ast.parse((root / 'graph.generated.bzl').read_text())
    values = [ast.literal_eval(keyword.value) for node in ast.walk(tree) if isinstance(node, ast.Call)
              for keyword in node.keywords if keyword.arg == 'project_outputs']
    assert len(values) == 1 and project + '|net10.0' in values[0]
    directory, assembly, kind = values[0][project + '|net10.0']
    assert kind == 'Exe' and assembly == 'System.IO.Pipelines.Tests.dll'
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
        'msbuild_runtime(name="suite_host",layout=":suite_source_runtime",entry_point="host.sh",runtime_identifier="linux-arm64",version="10.0.0")',
        'msbuild_graph_test(name="pipelines_suite",graph=":graph",project=' + json.dumps(project) + ',framework="net10.0",runtime_host=":suite_host",test_protocol="vstest",test_runner=":suite_runner",test_adapters=[":suite_adapter"],test_settings_output=".runsettings",size="large")']
    with (root / 'BUILD.bazel').open('a') as build:
        build.write('\n' + '\n'.join(lines) + '\n')
    (root / 'suite.json').write_text(json.dumps(dict(project=project, directory=directory, assembly=assembly,
        target='//:pipelines_suite', host='suite_source_runtime.layout', inventory=inventory), indent=2) + '\n')
    print(root, flush=True)


if __name__ == '__main__':
    main()
