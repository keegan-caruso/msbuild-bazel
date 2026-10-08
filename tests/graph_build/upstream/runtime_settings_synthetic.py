"""Qualify SDK-filter composition and failure/restoration through public Bazel rules."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='new disposable Linux ARM64 fixture')
    parser.add_argument('--version', choices=['8.8.0', '9.3.0'], default='9.3.0')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    base = args.directory.resolve()
    base.mkdir(parents=True, exist_ok=False)
    workspace = base / 'workspace'
    workspace.mkdir()
    tool = workspace / 'tool'
    tool.mkdir()
    shutil.copyfile(Path(__file__).with_name('RuntimeTestSettings.cs.txt'), tool / 'Program.cs')
    shutil.copyfile(Path(__file__).with_name('runtime_test_settings.bzl'), workspace / 'settings.bzl')
    (tool / 'Settings.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
    (tool / 'contract.json').write_text(json.dumps(dict(Version=1, Entry='Settings.csproj', SdkVersion='10.0.400',
        Properties=dict(Configuration='Release'), SharedInputs=[], Projects={'Settings.csproj': dict(Inputs=['Settings.csproj', 'Program.cs'],
        OutputDirectories=['bin/Release/net10.0', 'obj/Release/net10.0'])}), indent=2) + '\n')
    source = workspace / 'filtered.runsettings'
    original = '<RunSettings><RunConfiguration><DotNetHostPath>SDK-sentinel</DotNetHostPath><TestCaseFilter>Category!=OuterLoop</TestCaseFilter></RunConfiguration></RunSettings>'
    source.write_text(original)
    (workspace / 'empty.runsettings').write_text('<RunSettings><RunConfiguration><DotNetHostPath>other-sentinel</DotNetHostPath></RunConfiguration></RunSettings>')
    (workspace / 'MODULE.bazel').write_text('module(name="runtime_settings_fixture")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n'
        'local_path_override(module_name="rules_msbuild",path=' + json.dumps(str(ROOT)) + ')\n'
        'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
        'dotnet.sdk(name="dotnet",global_json="@rules_msbuild//:global.json")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
    (workspace / 'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph","msbuild_graph_runner","msbuild_graph_layout","msbuild_layout")
load(":settings.bzl","runtime_test_settings")
msbuild_graph_runner(name="runner")
msbuild_graph(name="tool",runner=":runner",contract="tool/contract.json",source_root="tool",srcs=["tool/Settings.csproj","tool/Program.cs"],linux_stable_paths=True,linux_worker=True,project_outputs={"Settings.csproj|net10.0":["bin/Release/net10.0","Settings.dll","Exe"]})
msbuild_graph_layout(name="tool_layout",graph=":tool",project="Settings.csproj",framework="net10.0")
msbuild_layout(name="filtered_layout",paths={"filtered.runsettings":".runsettings"})
msbuild_layout(name="empty_layout",paths={"empty.runsettings":".runsettings"})
runtime_test_settings(name="filtered",tool=":tool_layout",layout=":filtered_layout",filter="FullyQualifiedName~NetworkStream")
runtime_test_settings(name="empty",tool=":tool_layout",layout=":empty_layout",filter="FullyQualifiedName~NetworkStream")
''')
    bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base=' + str(base / 'output-base')]
    environment = dict(os.environ, USE_BAZEL_VERSION=args.version)
    for key in ['RULES_MSBUILD_PROJECT_CACHE_URL', 'RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN']:
        environment.pop(key, None)
    def run(label, success=True):
        bep = base / (label + '.bep')
        with (base / (label + '.log')).open('w') as log:
            result = subprocess.run(bazel + ['build', '//:filtered', '//:empty', '--jobs=1', '--worker_sandboxing',
                '--strategy=MSBuildGraph=worker', '--worker_max_instances=MSBuildGraph=1', '--remote_cache=', '--disk_cache=',
                '--build_event_json_file=' + str(bep)], cwd=workspace, env=environment, stdout=log, stderr=subprocess.STDOUT)
        assert (result.returncode == 0) == success, label
        events = [json.loads(line) for line in bep.read_text().splitlines()]
        metrics = next(event['buildMetrics']['actionSummary'] for event in events if 'buildMetrics' in event)
        compiles = sum(int(row.get('actionsExecuted', 0)) for row in metrics.get('actionData', []) if row['mnemonic'] == 'MSBuildGraph')
        assert compiles == int(label == 'seed'), metrics
        if success:
            filtered = ET.parse(workspace / 'bazel-bin/filtered.runsettings').getroot()
            empty = ET.parse(workspace / 'bazel-bin/empty.runsettings').getroot()
            assert filtered.findtext('RunConfiguration/DotNetHostPath') == 'SDK-sentinel'
            assert filtered.findtext('RunConfiguration/TestCaseFilter') == '(Category!=OuterLoop)&(FullyQualifiedName~NetworkStream)'
            assert empty.findtext('RunConfiguration/DotNetHostPath') == 'other-sentinel'
            assert empty.findtext('RunConfiguration/TestCaseFilter') == '(FullyQualifiedName~NetworkStream)'
        else:
            assert 'Missing SDK RunConfiguration' in (base / (label + '.log')).read_text()
        print(json.dumps(dict(case=label, success=success, compilerActions=compiles)), flush=True)
    try:
        run('seed')
        source.write_text('<RunSettings/>')
        run('missing-configuration', False)
        source.write_text(original)
        run('restored')
        (base / 'summary.json').write_text(json.dumps(dict(platform='linux-arm64', version=args.version,
            combinedFilter=True, missingFilterCreated=True, otherFieldsPreserved=True, rejectedMissingConfiguration=True,
            restoredWithoutCompilation=True), indent=2) + '\n')
    finally:
        source.write_text(original)
        subprocess.run(bazel + ['shutdown'], cwd=workspace, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
