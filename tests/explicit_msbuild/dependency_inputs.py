"""Dependency roles, SDK-only invalidation, fresh workers and cache replay.

Run in a disposable Linux toolchain environment: this temporarily adds an SDK
marker to prove build tooling does not enter application/test runfiles.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
bazel = os.environ['RULES_MSBUILD_BAZEL']
out = Path(sys.argv[1]).resolve()
out.mkdir(parents=True, exist_ok=False)
w = out / 'src'
w.mkdir()
base = out / 'base'
cache = out / 'cache'
rows = []
marker = sdk / 'sdk' / 'rules-msbuild-input-audit.txt'
if marker.exists():
    raise RuntimeError('Refusing to overwrite existing SDK marker')


def put(name, text):
    path = w / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def invoke(args):
    return subprocess.run([bazel, '--host_jvm_args=-Xmx768m', '--output_base=' + str(base), '--ignore_all_rc_files'] + args, cwd=w, capture_output=True, text=True, timeout=300)


def actions(path):
    text = path.read_text()
    decoder = json.JSONDecoder()
    result = []
    while text.strip():
        row, end = decoder.raw_decode(text.lstrip())
        result.append(row)
        text = text.lstrip()[end:]
    return result


def run(case, compiled, tested, value=1, data="first"):
    log = out / (case + '.execution.json')
    result = invoke(['test', '//:app', '--jobs=2', '--strategy=MSBuildAssembly=worker', '--worker_max_instances=MSBuildAssembly=1', '--disk_cache=' + str(cache), '--remote_cache=', '--remote_download_outputs=all', '--test_output=all', '--output_groups=+diagnostics', '--execution_log_json_file=' + str(log)])
    (out / (case + '.log')).write_text(result.stdout + result.stderr)
    assert result.returncode == 0, (case, result.stdout[-2000:], result.stderr[-5000:])
    assert f'RESULT={value}|{data}' in result.stdout + result.stderr, case
    entries = actions(log)
    builds = sorted(r['targetLabel'] for r in entries if r.get('mnemonic') == 'MSBuildAssembly' and not r.get('cacheHit'))
    tests = any(r.get('mnemonic') == 'TestRunner' and not r.get('cacheHit') for r in entries)
    assert builds == sorted(compiled), (case, builds, compiled)
    assert tests == tested, (case, tests, tested)
    payload = {}
    for name in ['leaf', 'middle', 'app']:
        for path in sorted((w / 'bazel-bin' / (name + '.runtime')).rglob('*')):
            if path.is_file():
                payload[name + '/' + str(path.relative_to(w / 'bazel-bin' / (name + '.runtime')))] = hashlib.sha256(path.read_bytes()).hexdigest()
    references = {name: hashlib.sha256(next((w/'bazel-bin'/(name+'.reference')).glob('*.dll')).read_bytes()).hexdigest() for name in ['leaf', 'middle', 'app']}
    # A real ASP.NET framework assembly is loaded without any SDK in runfiles.
    files = list((w / 'bazel-bin/app.runfiles').rglob('*'))
    assert not any(any(part in str(f.relative_to(w / 'bazel-bin/app.runfiles')) for part in ['/sdk/sdk/', '/sdk/packs/']) for f in files if f.is_file()), case
    assert any(f.name == 'Microsoft.AspNetCore.Http.Abstractions.dll' for f in files), case
    workers = {label: json.loads((w/'bazel-bin'/(label.split(':')[-1]+'.diagnostics')/'worker.json').read_text())['processId'] for label in builds}
    if case == 'cache-replay':
        recovered = [r for r in entries if r.get('mnemonic') == 'MSBuildAssembly']
        assert len(recovered) == 3 and all(r.get('cacheHit') for r in recovered), recovered
    row = dict(case=case, compiled=builds, testExecuted=tests, workerProcesses=workers, references=references, payloads=payload)
    rows.append(row)
    (out/'report.json').write_text(json.dumps(rows, indent=2)+'\n')
    print(case, builds, tests, flush=True)
    return row


put('MODULE.bazel', f'''module(name="dependency_inputs")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(root))})
dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")
dotnet.sdk(name="dotnet",version="10.0.400")
use_repo(dotnet,"dotnet")
register_toolchains("@dotnet//:all")
''')
put('BUILD.bazel', '''load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_test")
msbuild_library(name="leaf",project="Leaf/Leaf.csproj",srcs=["Leaf/Code.cs"],target_framework="net10.0",linux_worker=True,data=["payload.txt"])
msbuild_library(name="middle",project="Middle/Middle.csproj",srcs=["Middle/Code.cs"],target_framework="net10.0",deps=[":leaf"],linux_worker=True)
msbuild_test(name="app",project="App/App.csproj",srcs=["App/Code.cs"],target_framework="net10.0",deps=[":middle"],framework_refs=["Microsoft.AspNetCore.App"],use_apphost=False,linux_worker=True)
''')
project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>{}</Project>'
put('Leaf/Leaf.csproj', project.format(''))
put('Middle/Middle.csproj', project.format('<ItemGroup><ProjectReference Include="../Leaf/Leaf.csproj"/></ItemGroup>'))
put('App/App.csproj', project.format('<ItemGroup><ProjectReference Include="../Middle/Middle.csproj"/><FrameworkReference Include="Microsoft.AspNetCore.App"/></ItemGroup>'))
leaf = 'public static class Leaf { public static int Value() => 1; }'
put('Leaf/Code.cs', leaf)
put('Middle/Code.cs', 'public static class Middle { public static int Value() => Leaf.Value(); }')
put('App/Code.cs', '''System.Console.WriteLine(typeof(Microsoft.AspNetCore.Http.HttpContext).Assembly.FullName);
System.Console.WriteLine("RESULT=" + Middle.Value() + "|" + System.IO.File.ReadAllText("payload.txt"));
return System.IO.File.ReadAllText("payload.txt").Length > 0 && Middle.Value() > 0 ? 0 : 1;''')
put('payload.txt', 'first')
try:
    marker.write_text('first')
    initial = run('baseline', ['//:leaf', '//:middle', '//:app'], True)
    run('noop', [], False)
    put('Leaf/Code.cs', leaf.replace('=> 1', '=> 2'))
    body = run('body', ['//:leaf'], True, value=2)
    assert body['references'] == initial['references']
    assert body['workerProcesses']['//:leaf'] == initial['workerProcesses']['//:leaf']
    put('Leaf/Code.cs', leaf.replace('}', 'public static int Added() => 3; }'))
    api = run('api', ['//:leaf', '//:middle', '//:app'], True)
    assert api['references']['middle'] == initial['references']['middle']
    put('payload.txt', 'second')
    data = run('runtime-data', [], True, data='second')
    assert data['payloads'] == api['payloads']
    marker.write_text('second')
    tooling = run('sdk-only', ['//:leaf', '//:middle', '//:app'], False, data='second')
    assert tooling['payloads'] == data['payloads']
    assert invoke(['shutdown']).returncode == 0
    base = out / 'fresh-base'
    cache = out / 'empty-cache'
    fresh = run('fresh-execution', ['//:leaf', '//:middle', '//:app'], True, data='second')
    assert fresh['payloads'] == tooling['payloads']
    assert fresh['references'] == tooling['references']
    assert fresh['workerProcesses']['//:leaf'] != tooling['workerProcesses']['//:leaf']
    assert invoke(['shutdown']).returncode == 0
    base = out / 'recovery-base'
    replay = run('cache-replay', [], False, data='second')
    assert replay['payloads'] == fresh['payloads']
finally:
    try:
        invoke(['shutdown'])
    finally:
        marker.unlink(missing_ok=True)
