"""Prove reference-boundary invalidation against raw MSBuild on chain/fan-out graphs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output', type=Path)
p.add_argument('--repetitions', type=int, default=3)
p.add_argument('--force-transitive', action='store_true', help='Reproduce the old generated reference mode despite the project opt-out')
p.add_argument('--modes', nargs='+', choices=['transitive', 'private', 'direct'], default=['transitive', 'private', 'direct'])
p.add_argument('--widths', nargs='+', type=int, default=[1, 8])
a = p.parse_args()
root = Path(__file__).resolve().parents[2]
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
w = out / 'workspace'
w.mkdir()
raw = out / 'raw'
raw.mkdir()
bazel = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base=' + str(out / 'base'), '--host_jvm_args=-Xmx1024m', '--ignore_all_rc_files']
dotnet = str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']) / 'dotnet')
rows = []

def put(base, name, text):
    f = base / name
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)

def invoke(name, cmd, cwd, fail=False):
    start = time.monotonic()
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    (out / (name + '.log')).write_text(r.stdout + r.stderr)
    assert (r.returncode != 0) == fail, (name, r.returncode, (r.stdout + r.stderr)[-4000:])
    return round(time.monotonic() - start, 3)

def actions(path):
    text = path.read_text()
    offset = 0
    decoder = json.JSONDecoder()
    result = []
    while offset < len(text):
        if text[offset].isspace():
            offset += 1
            continue
        (row, offset) = decoder.raw_decode(text, offset)
        result.append(row)
    return result

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>{}</PropertyGroup><ItemGroup>{}</ItemGroup></Project>'

def fixture(mode, width):
    for base in [w, raw]:
        for name in ['C', 'B', 'Unrelated', *['A' + str(i) for i in range(width)]]:
            deps = '' if name in ['C', 'Unrelated'] else '<ProjectReference Include="../' + ('C/C' if name == 'B' else 'B/B') + '.csproj"' + (' PrivateAssets="all"' if mode == 'private' and name == 'B' else '') + '/>'
            prop = '<DisableTransitiveProjectReferences>true</DisableTransitiveProjectReferences>' if mode == 'direct' and name.startswith('A') else ''
            put(base, name + '/' + name + '.csproj', project.format(prop, deps))
            code = 'public static class C { public const int Number = 1; public static int Value() => 1; }' if name == 'C' else 'public static class B { public const int Number = C.Number; public static int Value() => C.Value(); }' if name == 'B' else 'public class Unrelated {}' if name == 'Unrelated' else 'public static class ' + name + ' { public static int Value() => B.Value(); public const int Number = B.Number; }'
            put(base, name + '/Code.cs', code)
        refs = ''.join(('<ProjectReference Include="' + name + '/' + name + '.csproj"/>' for name in ['Unrelated', *['A' + str(i) for i in range(width)]]))
        put(base, 'Graph.proj', '<Project><ItemGroup>' + refs + '</ItemGroup><Target Name="Restore"><MSBuild Projects="@(ProjectReference)" Targets="Restore" BuildInParallel="true"/></Target><Target Name="Build"><MSBuild Projects="@(ProjectReference)" Targets="Build" BuildInParallel="true"/></Target></Project>')
    for name in ['global.json', '.bazelversion']:
        shutil.copyfile(root / name, w / name)
        shutil.copyfile(root / name, raw / name)
    put(w, 'MODULE.bazel', 'module(name="reference_invalidation")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path=' + json.dumps(str(root)) + ')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",global_json="//:global.json")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
    mapping = {'projectDefaults': {'linuxWorker': True}, 'projects': {}}
    if mode == 'private':
        mapping['projects'] = {'B/B.csproj': {'projectReferences': {'C/C.csproj': {'role': 'private', 'label': ':C_C'}}}}
    if a.force_transitive and mode == 'direct':
        mapping['projects'] = {f'A{i}/A{i}.csproj': {'transitiveCompileReferences': True} for i in range(width)}
    put(w, 'sync.json', json.dumps(mapping))
    entries = [f'A{i}/A{i}.csproj' for i in range(width)] + ['Unrelated/Unrelated.csproj', 'C/C.csproj']
    authored = 'load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\nexports_files(["global.json"])\nmsbuild_sync(name="sync",projects=' + json.dumps(entries) + ',mappings="sync.json")\n'
    put(w, 'BUILD.bazel', authored)
    invoke(mode + '-sync', bazel + ['run', '//:sync', '--jobs=2'], w)
    put(w, 'BUILD.bazel', 'load(":projects.generated.bzl","app_projects")\n' + authored + 'app_projects()\n')
    targets = [f'//:A{i}_A{i}' for i in range(width)] + ['//:Unrelated_Unrelated']
    return targets

def build(name, targets):
    log = out / (name + '.execution.json')
    sec = invoke(name, bazel + ['build', *targets, '--jobs=2', '--worker_max_instances=MSBuildAssembly=2', '--experimental_total_worker_memory_limit_mb=4096', '--experimental_shrink_worker_pool', '--remote_download_outputs=all', '--disk_cache=' + str(out / 'cache'), '--execution_log_json_file=' + str(log)], w)
    executed = sorted({r['targetLabel'].split(':')[1] for r in actions(log) if r.get('mnemonic') == 'MSBuildAssembly' and (not r.get('cacheHit'))})
    hashes = {n: digest(w / 'bazel-bin' / f'{n}_{n}_net10_0.reference' / f'{n}.dll') for n in ['C', 'B', 'A0']}
    return (sec, executed, hashes)
try:
    for width in a.widths:
        for mode in a.modes:
            targets = fixture(mode, width)
            tag = f'{mode}-{width}'
            build(tag + '-initial', targets)
            invoke(tag + '-raw-restore', [dotnet, 'msbuild', 'Graph.proj', '/t:Restore', '/p:Configuration=Release', '/m:2', '/clp:PerformanceSummary'], raw)
            invoke(tag + '-raw-initial', [dotnet, 'msbuild', 'Graph.proj', '/t:Build', '/p:Configuration=Release', '/m:2', '/clp:PerformanceSummary'], raw)
            original = (w / 'C/Code.cs').read_text()
            (_, _, before) = build(tag + '-noop', targets)
            raw_before = {n: digest(raw / n / 'obj/Release/net10.0/ref' / f'{n}.dll') for n in ['C', 'B', 'A0']}
            for case in ['body', 'addition', 'constant']:
                for i in range(a.repetitions):
                    value = str(width * 100 + ['transitive', 'private', 'direct'].index(mode) * 10 + i + 2)
                    changed = original.replace('Value() => 1;', f'Value() => 1 + ({value} - {value});') if case == 'body' else original.replace('public const int Number', f'public static int Added{value}() => 1; public const int Number') if case == 'addition' else original.replace('Number = 1;', f'Number = {value};')
                    for base in [w, raw]:
                        put(base, 'C/Code.cs', changed)
                    name = f'{tag}-{case}-{i}'

                    def raw_build():
                        return invoke(name + '-raw', [dotnet, 'msbuild', 'Graph.proj', '/t:Build', '/p:Configuration=Release', '/m:2', '/clp:PerformanceSummary'], raw)
                    if i % 2:
                        rs = raw_build()
                    (sec, compiled, after) = build(name, targets)
                    if not i % 2:
                        rs = raw_build()
                    expected = ['C_C_net10_0'] if case == 'body' else ['C_C_net10_0', 'B_B_net10_0'] + ([f'A{j}_A{j}_net10_0' for j in range(width)] if case == 'constant' or mode == 'transitive' or (mode == 'direct' and a.force_transitive) else [])
                    assert compiled == sorted(expected), (name, compiled, expected)
                    assert (after['B'] == before['B']) == (case != 'constant'), (name, 'B reference')
                    assert (after['A0'] == before['A0']) == (case != 'constant'), (name, 'A reference')
                    raw_changed = {n: digest(raw / n / 'obj/Release/net10.0/ref' / f'{n}.dll') != raw_before[n] for n in ['C', 'B', 'A0']}
                    assert raw_changed == {n: after[n] != before[n] for n in after}, (name, raw_changed)
                    row = dict(graph=mode, width=width, forcedTransitive=a.force_transitive, case=case, repetition=i, bazelSeconds=sec, rawSeconds=rs, compiled=compiled, referenceChanged={n: after[n] != before[n] for n in after}, rawReferenceChanged=raw_changed)
                    rows.append(row)
                    print(row, flush=True)
                    (out / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
                    for base in [w, raw]:
                        put(base, 'C/Code.cs', original)
                    (_, reverted, _) = build(name + '-revert', targets)
                    assert not reverted, (name, reverted)
                    invoke(name + '-raw-revert', [dotnet, 'msbuild', 'Graph.proj', '/t:Build', '/p:Configuration=Release', '/m:2', '/clp:PerformanceSummary'], raw)
finally:
    subprocess.run(bazel + ['shutdown'], cwd=w, check=True)
    subprocess.run([dotnet, 'build-server', 'shutdown'], cwd=raw, check=True)
