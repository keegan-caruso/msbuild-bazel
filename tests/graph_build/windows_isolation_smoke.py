"""Positive-only native Windows declared-SDK isolated sync/build smoke."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from fixture_host import ROOT, WINDOWS, bazel_environment, bazel_startup, sdk_declaration


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path, help='Fresh owned fixture and evidence directory')
    args = parser.parse_args()
    if not WINDOWS:
        raise SystemExit('Requires native Windows x64 or ARM64')
    base = args.directory.resolve()
    base.mkdir()
    environment = bazel_environment()
    for name in ['RULES_MSBUILD_PROJECT_CACHE_URL', 'RULES_MSBUILD_PROJECT_CACHE_BEARER_TOKEN',
                 'RULES_MSBUILD_PROJECT_CACHE_READ_ONLY', 'RULES_MSBUILD_GRAPH_LOCAL_STATE',
                 'RULES_MSBUILD_GRAPH_PREPARED_RESTORE', 'RULES_MSBUILD_GRAPH_READONLY_PACKAGES']:
        environment.pop(name, None)
    receipts = []

    def run(name, command, cwd=ROOT):
        started = time.monotonic()
        with (base / (name + '.out')).open('w') as output, (base / (name + '.err')).open('w') as error:
            result = subprocess.run(list(map(str, command)), cwd=cwd, env=environment, stdin=subprocess.DEVNULL,
                                    stdout=output, stderr=error, timeout=900)
        receipts.append(dict(name=name, exitCode=result.returncode, seconds=time.monotonic() - started))
        (base / 'receipts.json').write_text(json.dumps(receipts, indent=2) + '\n')
        assert result.returncode == 0, f'{name} failed: {base / (name + ".err")}'
        return (base / (name + '.out')).read_text()

    abi = json.loads(run('abi', [sys.executable, ROOT / 'tests/graph_build/windows_abi.py']))
    assert abi['native'] and abi['os'] == abi['process'] and abi['process'] in ('X64', 'Arm64'), abi
    storage = Path(abi['storage'])
    before = set(storage.iterdir()) if storage.exists() else set()
    workspace = base / 'workspace'
    workspace.mkdir()
    (workspace / 'global.json').write_bytes((ROOT / 'global.json').read_bytes())
    (workspace / 'MODULE.bazel').write_text(
        'module(name="windows_isolation_smoke")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n'
        f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})\n'
        'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
        + sdk_declaration(global_json='//:global.json') + 'use_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
    for directory in ['App', 'Lib']:
        (workspace / directory).mkdir()
    (workspace / 'Lib/Lib.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net11.0</TargetFramework></PropertyGroup></Project>')
    (workspace / 'Lib/Message.cs').write_text('public static class Message { public static string Value => "isolated Windows "; }')
    (workspace / 'App/App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net11.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Lib/Lib.csproj" /></ItemGroup></Project>')
    (workspace / 'App/Program.cs').write_text('System.Console.WriteLine(Message.Value + System.Runtime.InteropServices.RuntimeInformation.ProcessArchitecture);')
    sync = ('load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\n'
            'msbuild_sync(name="sync",projects=["App/App.csproj"],srcs=["App/App.csproj","App/Program.cs","Lib/Lib.csproj","Lib/Message.cs","global.json"],windows_isolation=True)\n')
    build = workspace / 'BUILD.bazel'
    build.write_text(sync)
    prefix = bazel_startup('--output_base=' + str(base / 'bazel'))
    uncached = ['--remote_cache=', '--disk_cache=', '--remote_executor=', '--noremote_accept_cached']

    def executed(path, mnemonic):
        text = path.read_text()
        decoder = json.JSONDecoder()
        rows = []
        while text.strip():
            text = text.lstrip()
            item, end = decoder.raw_decode(text)
            rows.append(item)
            text = text[end:]
        selected = [row for row in rows if row.get('mnemonic') == mnemonic]
        assert len(selected) == 1 and not selected[0].get('cacheHit') and selected[0].get('exitCode', 0) == 0, [{key: row.get(key) for key in ['mnemonic', 'runner', 'cacheHit', 'exitCode']} for row in selected]
        return selected[0]

    try:
        run('sync', [*prefix, 'run', *uncached, '--execution_log_json_file=' + str(base / 'sync-execution.json'), '//:sync'], workspace)
        sync_action = executed(base / 'sync-execution.json', 'MSBuildSyncPrepare')
        assert any('windows-sync' in argument for argument in sync_action['commandArgs']), sync_action
        generated = {name: (workspace / name).read_bytes() for name in ['graph.generated.json', 'graph.generated.bzl']}
        assert set(json.loads(generated['graph.generated.json'])['Projects']) == {'App/App.csproj', 'Lib/Lib.csproj'}
        build.write_text('load(":graph.generated.bzl","app_graph")\n' + sync + 'app_graph(name="graph",windows_isolation=True)\n')
        run('graph', [*prefix, 'build', *uncached, '--execution_log_json_file=' + str(base / 'graph-execution.json'), '//:graph'], workspace)
        graph_action = executed(base / 'graph-execution.json', 'MSBuildGraph')
        # run_shell passes $0 after the -c command, then the eleven graph options
        # followed by source/destination pairs. Isolation is option eleven.
        parameters = graph_action['commandArgs'][graph_action['commandArgs'].index('-c') + 3:]
        assert len(parameters) >= 11 and parameters[10] == '1', parameters
        assert any('windows-sandbox' in argument for argument in graph_action['commandArgs']), graph_action['commandArgs']
        output = Path(run('bin-path', [*prefix, 'info', 'bazel-bin'], workspace).strip()) / 'graph.graph/workspace/App/bin/Release/net11.0/App.dll'
        dotnet = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']) / 'dotnet.exe'
        assert run('app', [dotnet, output], workspace).strip() == 'isolated Windows ' + abi['process']
        run('sync-check', [*prefix, 'run', *uncached, '//:sync', '--', '--check'], workspace)
        assert all((workspace / name).read_bytes() == contents for name, contents in generated.items())
        after = set(storage.iterdir()) if storage.exists() else set()
        assert not after - before, 'New owned sandbox lease remains after successful operations'
        (base / 'result.json').write_text(json.dumps(dict(abi=abi, generated={name: hashlib.sha256(contents).hexdigest() for name, contents in generated.items()}, normalCleanup=True, graphIsolationArgument=parameters[10], appHost='selected native dotnet.exe', executedActions=[{key: action.get(key) for key in ['mnemonic', 'runner', 'cacheHit', 'exitCode', 'targetLabel']} for action in [sync_action, graph_action]], receipts=receipts), indent=2) + '\n')
    finally:
        run('shutdown', [*prefix, 'shutdown'], workspace)
    print('PASS: native Windows isolated two-project sync/build, app output, sync check and normal cleanup')


if __name__ == '__main__':
    main()
