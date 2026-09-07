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

BAZEL = Path(os.environ.get('SPIKE_BAZEL', ROOT / '.tools/bin/bazel'))

def probe(output, root_project=False):
    with BazelSession(output) as bazel:
        return _probe(output, root_project, bazel)


def _probe(output, root_project, bazel):
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
    dotnet = DOTNET_ROOT / 'dotnet'
    run('exporter-build', [dotnet, 'build', ROOT / 'tools/GraphExport', '-c', 'Release', '--nologo'], ROOT)
    run('restore', [dotnet, 'msbuild', entry, '-t:Restore', '-p:Configuration=Release', '-nologo'])
    manifest = output / 'manifest.json'
    request = output / 'export-request.json'
    request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(workspace), dotnetRoot=str(DOTNET_ROOT), sdkVersion='10.0.100', packageRoot=str(workspace / '.nuget/packages'), entryPoints=[dict(project=entry, globalProperties={'Configuration':'Release'})], output=str(manifest))))
    run('export', [dotnet, ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request])
    generated = output / 'workspace'
    graph = prepare(workspace, manifest, generated)
    run('baseline', [dotnet, 'msbuild', entry, '-t:Build', '-p:Configuration=Release', '-graphBuild', '-isolateProjects', '-nologo'])
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
    parser.add_argument('--root-project', action='store_true')
    args = parser.parse_args()
    print(json.dumps(probe(args.output, args.root_project), indent=2))
