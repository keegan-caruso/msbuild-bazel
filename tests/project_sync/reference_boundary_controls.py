"""Direct-reference failures, runtime invalidation and independent cache recovery.

Seed/recover run in separate source-only containers; stop the producer first.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output', type=Path)
p.add_argument('--cache', required=True)
p.add_argument('--expect', type=Path)
a = p.parse_args()
root = Path(__file__).resolve().parents[2]
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
w = out / 'workspace'
w.mkdir()
raw = out / 'raw'
raw.mkdir()
start = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base=' + str(out / 'base'), '--host_jvm_args=-Xmx1024m', '--ignore_all_rc_files']
flags = ['--jobs=2', '--action_env=PATH=/usr/bin:/bin', '--test_env=PATH=/usr/bin:/bin', '--remote_cache=' + a.cache, '--remote_upload_local_results=' + str(not a.expect).lower(), '--disk_cache=', '--remote_download_outputs=all']
dotnet = str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']) / 'dotnet')
rows = []

def put(base, name, text):
    f = base / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>{}</PropertyGroup><ItemGroup>{}</ItemGroup></Project>'
c = 'public static class C { public static int Value() => 1; } public class Token {}'
b = 'public static class B { public static int Value() => C.Value(); }'
x = 'public static class A { public static int Value() => B.Value(); }'
for base in [w, raw]:
    put(base, 'C/C.csproj', project.format('', ''))
    put(base, 'C/Code.cs', c)
    put(base, 'B/B.csproj', project.format('', '<ProjectReference Include="../C/C.csproj"/>'))
    put(base, 'B/Code.cs', b)
    put(base, 'A/A.csproj', project.format('<DisableTransitiveProjectReferences>true</DisableTransitiveProjectReferences>', '<ProjectReference Include="../B/B.csproj"/>'))
    put(base, 'A/Code.cs', x)
    put(base, 'App/App.csproj', project.format('<OutputType>Exe</OutputType>', '<ProjectReference Include="../A/A.csproj"/>'))
    put(base, 'App/Program.cs', 'return A.Value() == 1 ? 0 : 1;')
for name in ['global.json', '.bazelversion']:
    shutil.copyfile(root / name, w / name)
put(w, 'MODULE.bazel', 'module(name="reference_controls")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path=' + json.dumps(str(root)) + ')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",global_json="//:global.json")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
put(w, 'sync.json', json.dumps({'projectDefaults': {'linuxWorker': True}, 'tests': {'App/App.csproj': {'protocol': 'executable'}}}))
authored = 'load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\nexports_files(["global.json"])\nmsbuild_sync(name="sync",projects=["App/App.csproj"],mappings="sync.json")\n'
put(w, 'BUILD.bazel', authored)

def run(name, cmd, fail=False):
    execution = out / (name + '.execution.json')
    bep = out / (name + '.bep')
    r = subprocess.run(start + cmd + flags + ['--execution_log_json_file=' + str(execution), '--build_event_json_file=' + str(bep)], cwd=w, capture_output=True, text=True)
    text = r.stdout + r.stderr
    (out / (name + '.log')).write_text(text)
    assert (r.returncode != 0) == fail, (name, text[-5000:])
    data = execution.read_text()
    offset = 0
    decoder = json.JSONDecoder()
    actions = []
    while offset < len(data):
        if data[offset].isspace():
            offset += 1
            continue
        (v, offset) = decoder.raw_decode(data, offset)
        actions.append(v)
    row = dict(case=name, exitCode=r.returncode, compiled=sorted({v['targetLabel'].split(':')[1] for v in actions if v.get('mnemonic') == 'MSBuildAssembly' and (not v.get('cacheHit'))}), tested=sorted({v['targetLabel'].split(':')[1] for v in actions if v.get('mnemonic') == 'TestRunner' and (not v.get('cacheHit'))}), remoteHits=sum((v.get('runner') == 'remote cache hit' for v in actions)))
    rows.append(row)
    print(row, flush=True)
    return (row, actions, [json.loads(line) for line in bep.read_text().splitlines()], text)

def sync(name):
    r = subprocess.run(start + ['run', '//:sync', *flags], cwd=w, capture_output=True, text=True)
    (out / (name + '.log')).write_text(r.stdout + r.stderr)
    assert r.returncode == 0, r.stderr
    put(w, 'BUILD.bazel', 'load(":projects.generated.bzl","app_projects")\n' + authored + 'app_projects()\n')

def raw_build(name, fail=False):
    r = subprocess.run([dotnet, 'build', 'App/App.csproj', '-c', 'Release', '-m:2'], cwd=raw, capture_output=True, text=True)
    (out / (name + '-raw.log')).write_text(r.stdout + r.stderr)
    assert (r.returncode != 0) == fail, (name, r.stdout + r.stderr)
    return r.stdout + r.stderr

def hashes():
    return {str(f.relative_to(w / 'bazel-out')): hashlib.sha256(f.read_bytes()).hexdigest() for f in (w / 'bazel-out').rglob('*') if f.is_file() and (any((v.endswith('.runtime') for v in f.parts)) or (f.suffix == '.dll' and any((v.endswith('.reference') for v in f.parts))))}
try:
    sync('sync')
    generated = (w / 'projects.generated.bzl').read_bytes()
    (row, actions, events, _) = run('initial', ['test', '//:App_App'] + ([] if a.expect else ['--remote_accept_cached=false']))
    initial = hashes()
    assert initial
    request = json.loads((w / 'bazel-bin/A_A_net10_0.request.json').read_text())
    assert [Path(v).name for v in request['references']] == ['B.dll'], request['references']
    if a.expect:
        assert initial == json.loads(a.expect.read_text())['hashes']
        assert all((v.get('cacheHit') for v in actions))
        assert any((e.get('testResult', {}).get('executionInfo', {}).get('cachedRemotely') for e in events))
        (row, _, _, _) = run('forced', ['test', '//:App_App', '--nocache_test_results'])
        assert row['compiled'] == [] and row['tested'] == ['App_App_net10_0']
    else:
        raw_build('initial')
        put(w, 'C/Code.cs', c.replace('=> 1', '=> 2'))
        (row, _, _, _) = run('body-failure', ['test', '//:App_App', '--remote_accept_cached=false'], True)
        assert row['compiled'] == ['C_C_net10_0'] and row['tested'] == ['App_App_net10_0']
        put(w, 'C/Code.cs', c)
        (row, _, _, _) = run('body-repair', ['test', '//:App_App'])
        assert not row['compiled'] and (not row['tested'])
        for (kind, bs, asource, diagnostic) in [('direct-use', b, x.replace('B.Value()', 'C.Value()'), 'CS0103'), ('exposed-type', b.replace('public static int Value()', 'public static Token Make() => new(); public static int Value()'), x.replace('B.Value()', 'B.Make() is null ? 0 : 1'), 'CS0012')]:
            for base in [w, raw]:
                put(base, 'B/Code.cs', bs)
                put(base, 'A/Code.cs', asource)
            (row, _, _, text) = run(kind, ['test', '//:App_App'], True)
            assert diagnostic in text
            assert diagnostic in raw_build(kind, True)
            for base in [w, raw]:
                f = base / 'A/A.csproj'
                f.write_text(f.read_text().replace('</ItemGroup>', '<ProjectReference Include="../C/C.csproj"/></ItemGroup>'))
            sync(kind + '-sync')
            run(kind + '-repair', ['test', '//:App_App'])
            raw_build(kind + '-repair')
            for base in [w, raw]:
                put(base, 'B/Code.cs', b)
                put(base, 'A/Code.cs', x)
                f = base / 'A/A.csproj'
                f.write_text(f.read_text().replace('<ProjectReference Include="../C/C.csproj"/>', ''))
            sync(kind + '-revert-sync')
            run(kind + '-revert', ['test', '//:App_App'])
            raw_build(kind + '-revert')
    assert (w / 'projects.generated.bzl').read_bytes() == generated
    (out / 'results.json').write_text(json.dumps(dict(records=rows, hashes=initial, ACompilerInputs=['B.dll'], generatedUnchanged=True, independentRecovery=bool(a.expect)), indent=2) + '\n')
finally:
    subprocess.run(start + ['shutdown'], cwd=w, check=True)
    if not a.expect:
        subprocess.run([dotnet, 'build-server', 'shutdown'], cwd=raw, check=True)
