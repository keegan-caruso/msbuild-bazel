#!/usr/bin/env python3
"""Retained native-sandbox evidence for the first exported graph execution slice."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from prepare_graph import prepare, ROOT, DOTNET_ROOT
from probe_bazel import json_stream
from bazel_session import BazelSession
sys.path.insert(0, str(ROOT / 'tests/graph'))
from test_export_graph import write_fixture

BAZEL = Path(os.environ.get('RULES_MSBUILD_BAZEL', ROOT / '.tools/bin/bazel'))

def probe(output, root_project=False, selected_reference=False, *, sdk_root=None, sdk_version="10.0.400", tool_framework=None):
    with BazelSession(output) as bazel:
        return _probe(output, root_project, selected_reference, bazel, sdk_root, sdk_version, tool_framework)


def _probe(output, root_project, selected_reference, bazel, sdk_root, sdk_version, tool_framework):
    dotnet_root = Path(sdk_root).resolve() if sdk_root else DOTNET_ROOT
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    workspace = output / 'preparation'
    write_fixture(workspace)
    entry = 'build.proj'
    app_project = 'src/App/App.csproj'
    if root_project:
        shutil.rmtree(workspace / 'src')
        for name in ('Directory.Build.props', 'Directory.Build.targets', 'build.proj'):
            (workspace / name).unlink()
        (workspace / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><UseAppHost>false</UseAppHost></PropertyGroup></Project>')
        (workspace / 'Program.cs').write_text('System.Console.WriteLine("root-project");')
        entry = app_project = 'App.csproj'
    if selected_reference:
        (workspace/'src/Shared/Shared.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework></TargetFramework><TargetFrameworks>net10.0;netstandard2.1</TargetFrameworks></PropertyGroup></Project>')
    binary = Path(app_project).parent / 'bin/Release/net10.0/App.dll'

    (workspace / '.nuget/packages').mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ, NUGET_PACKAGES=str(workspace / '.nuget/packages'), DOTNET_CLI_HOME=str(output / 'home'), DOTNET_NOLOGO='1', DOTNET_CLI_TELEMETRY_OPTOUT='1')
    def run(name, command, cwd=workspace):
        if str(command[0]) == str(BAZEL):
            command = bazel.prepare(command, cwd, environment)
        result = subprocess.run([str(a) for a in command], cwd=cwd, env=environment, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=300)
        (output / (name + '.log')).write_text(result.stdout)
        if result.returncode: raise RuntimeError(name + ' failed: ' + result.stdout)
        return result.stdout.strip()
    dotnet = dotnet_root / 'dotnet'
    engine = dotnet_root / 'sdk' / sdk_version / 'MSBuild.dll'
    environment.update(DOTNET_ROOT=str(dotnet_root), DOTNET_HOST_PATH=str(dotnet_root / 'dotnet'), MSBuildSDKsPath=str(engine.parent / 'Sdks'), DOTNET_MSBUILD_SDK_RESOLVER_CLI_DIR=str(dotnet_root), DOTNET_MSBUILD_SDK_RESOLVER_SDKS_DIR=str(engine.parent / 'Sdks'), DOTNET_MSBUILD_SDK_RESOLVER_SDKS_VER=sdk_version)
    run('exporter-build', [dotnet, 'exec', engine, ROOT / 'tools/GraphExport/GraphExport.csproj', '-restore', '-t:Build', '-p:Configuration=Release', '-p:RulesMSBuildToolTargetFramework=' + (tool_framework or 'net10.0'), '-nologo'], ROOT)
    run('restore', [dotnet, 'exec', engine, entry, '-t:Restore', '-p:Configuration=Release', '-nologo'])
    manifest = output / 'manifest.json'
    request = output / 'export-request.json'
    request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(workspace), dotnetRoot=str(dotnet_root), sdkVersion=sdk_version, packageRoot=str(workspace / '.nuget/packages'), entryPoints=[dict(project=entry, globalProperties={'Configuration':'Release'})], output=str(manifest))))
    run('export', [dotnet, ROOT / ('tools/GraphExport/bin/Release/' + (tool_framework or 'net10.0') + '/GraphExport.dll'), '--request', request])
    generated = output / 'workspace'
    graph = prepare(workspace, manifest, generated, sdk_root=dotnet_root, sdk_version=sdk_version, tool_framework=tool_framework)
    run('baseline', [dotnet, 'exec', engine, app_project if selected_reference else entry, '-t:Build', '-p:Configuration=Release', *([] if selected_reference else ['-graphBuild', '-isolateProjects']), '-nologo'])
    baseline = run('baseline-app', [dotnet, workspace / binary])
    shutil.rmtree(workspace)
    strategy = 'darwin-sandbox' if platform.system() == 'Darwin' else 'linux-sandbox'
    execution = output / 'execution.json'
    run('bazel', [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc', f'--output_base={output / "bazel-base"}', f'--output_user_root={output / "bazel-user"}', 'build', '//:all', f'--disk_cache={output / "disk-cache"}', f'--spawn_strategy={strategy}', f'--strategy=MsbuildProject={strategy}', '--jobs=2', '--noshow_progress', '--color=no', '--curses=no', f'--execution_log_json_file={execution}'], generated)
    nodes = {n['id']: n['project'].removeprefix('workspace/') for n in graph['nodes']}
    records = [r for r in json_stream(execution) if r.get('mnemonic') == 'MsbuildProject']
    actions = {}
    executed = []
    for record in records:
        identity = record['targetLabel'].split(':node_')[-1]
        project = nodes[identity]
        action = json.loads((generated / f'bazel-bin/node_{identity}.diagnostics/action.json').read_text())
        action.update(runner=record.get('runner'), cacheHit=record.get('cacheHit', False))
        actions[project] = action
        if not action['cacheHit']: executed.append(project)
    app = next(identity for identity, project in nodes.items() if project == app_project)
    actual = run('app', [dotnet, generated / f'bazel-bin/node_{app}.bundle/artifacts' / binary], generated)
    report = dict(schemaVersion=1, baselineOutput=baseline, output=actual, nodes=nodes, executedProjects=sorted(executed), actions=actions, preparationWorkspaceAbsent=not workspace.exists())
    report['bazelMode'] = bazel.mode
    (output / 'report.json').write_text(json.dumps(report, indent=2))
    return report

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--sdk-root', type=Path)
    parser.add_argument('--sdk-version', default='10.0.400')
    parser.add_argument('--tool-target-framework', choices=('net10.0', 'net11.0'))
    parser.add_argument('--root-project', action='store_true')
    parser.add_argument('--selected-reference', action='store_true')
    args = parser.parse_args()
    print(json.dumps(probe(args.output, args.root_project, args.selected_reference, sdk_root=args.sdk_root, sdk_version=args.sdk_version, tool_framework=args.tool_target_framework), indent=2))
