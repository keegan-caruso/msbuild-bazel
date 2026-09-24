"""Qualify SDK-only remote recovery and persistent-worker invalidation on Linux."""
import argparse
import json
import os
from pathlib import Path
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('directory', type=Path)
p.add_argument('--mode', choices=['seed', 'recover', 'workers'], required=True)
p.add_argument('--cache', default='')
a = p.parse_args()
if a.mode != 'workers' and not a.cache:
    p.error('seed/recover require --cache')
root = Path(__file__).resolve().parents[2]
evidence = a.directory.resolve()
evidence.mkdir(parents=True)
w = evidence / 'source'
w.mkdir()
(w / 'MODULE.bazel').write_text(f'''module(name="sdk_cache_workers")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(root))})
dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")
dotnet.sdk(name="dotnet",global_json="//:global.json",platforms=["linux-arm64"])
use_repo(dotnet,"dotnet")
register_toolchains("@dotnet//:all")
''')
(w / 'global.json').write_text('{"sdk":{"version":"10.0.400","rollForward":"disable"}}')
worker = a.mode == 'workers'
(w / 'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_test")
exports_files(["global.json"])
msbuild_library(name="lib",project="Lib.csproj",srcs=["Lib.cs"],target_framework="net10.0",linux_worker=%s)
msbuild_test(name="test",project="Test.csproj",srcs=["Test.cs"],deps=[":lib"],target_framework="net10.0",use_apphost=False,linux_worker=%s)
''' % (worker, worker))
(w / 'Lib.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
(w / 'Test.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><ProjectReference Include="Lib.csproj" /></ItemGroup></Project>')
original = 'public static class Lib { public static int Value() => 1; }'
(w / 'Lib.cs').write_text(original)
(w / 'Test.cs').write_text('System.Console.WriteLine("RUNTIME="+System.Environment.Version); return Lib.Value()==1 ? 0 : 1;')
base = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base='+str(evidence/'base'), '--ignore_all_rc_files']
records = []

def run(case, expected=0, compiled=None, flags=()):
    execution = evidence/(case+'.execution.json')
    command = base+['test', '//:test', '--jobs=2', '--test_output=all', '--lockfile_mode=off', '--disk_cache=', '--remote_cache='+a.cache, '--remote_upload_local_results='+str(a.mode=='seed').lower(), '--remote_download_outputs=all', '--execution_log_json_file='+str(execution)]
    if worker:
        command += ['--strategy=MSBuildAssembly=worker', '--worker_max_instances=MSBuildAssembly=1']
    result = subprocess.run(command+list(flags), cwd=w, text=True, capture_output=True)
    (evidence/(case+'.log')).write_text(result.stdout+result.stderr)
    assert result.returncode == expected, (case, result.stdout[-6000:]+result.stderr[-6000:])
    data = execution.read_text().strip(); decoder = json.JSONDecoder(); actions = []
    while data:
        action, end = decoder.raw_decode(data); actions.append(action); data = data[end:].lstrip()
    builds = [r for r in actions if r.get('mnemonic')=='MSBuildAssembly' and not r.get('cacheHit')]
    labels = sorted(r['targetLabel'] for r in builds)
    if compiled is not None:
        assert labels == compiled, (case, labels)
    if worker:
        assert all(r.get('runner')=='worker' for r in builds), builds
    interesting = [r for r in actions if r.get('mnemonic') in ['MSBuildAssembly','MSBuildRunnerBootstrap','DotnetSdkRuntime','TestRunner']]
    row = dict(case=case, compiled=labels, actions=[dict(mnemonic=r['mnemonic'],cached=r.get('cacheHit',False),runner=r.get('runner')) for r in interesting])
    if worker:
        worker_info = json.loads((w/'bazel-bin/lib.diagnostics/worker.json').read_text())
        row['workerProcessId'] = worker_info['processId']
        if records:
            if case == 'sdk-change':
                assert row['workerProcessId'] != records[-1]['workerProcessId'], row
            else:
                assert row['workerProcessId'] == records[-1]['workerProcessId'], row
    records.append(row)
    (evidence/'report.json').write_text(json.dumps(records,indent=2)+'\n')
    print(json.dumps(row),flush=True)
    return interesting

try:
    if a.mode == 'recover':
        actions = run('recovery', compiled=[])
        for mnemonic in ['MSBuildAssembly','MSBuildRunnerBootstrap','DotnetSdkRuntime','TestRunner']:
            matching = [r for r in actions if r['mnemonic']==mnemonic]
            assert matching and all(r.get('cacheHit') for r in matching), (mnemonic,matching)
    elif a.mode == 'seed':
        run('seed', compiled=['//:lib','//:test'])
    else:
        run('cold', compiled=['//:lib','//:test'])
        run('noop', compiled=[])
        (w/'Lib.cs').write_text(original.replace('=> 1','=> 2'))
        run('body', expected=3, compiled=['//:lib'])
        (w/'Lib.cs').write_text(original.replace('int Value()', 'int Value(int unused)'))
        run('api', expected=1, compiled=['//:lib','//:test'])
        (w/'Lib.cs').write_text(original)
        run('restored', compiled=['//:lib','//:test'])
        (w/'global.json').write_text('{"sdk":{"version":"10.0.401","rollForward":"disable"}}')
        run('sdk-change', compiled=['//:lib','//:test'])
        assert 'RUNTIME=10.0.12' in (evidence/'sdk-change.log').read_text()
finally:
    subprocess.run(base+['shutdown'],cwd=w,check=True)
