"""Small Bazel graphs proving stable metadata and reference cutoffs on Linux.

Requires the qualified worker SDK/image. The internal define is deliberately
experimental; package/tool/analyzer loading is outside this first slice.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('output', type=Path)
p.add_argument('--expected-baseline', type=Path, help='Compare with another fresh worker/workspace report')
p.add_argument('--legacy', action='store_true', help='Reproduce content-derived project path churn')
p.add_argument('--transitive', action='store_true', help='Keep C as an input to A and Fan')
a = p.parse_args()
root = Path(__file__).resolve().parents[2]
out = a.output.resolve()
out.mkdir(parents=True, exist_ok=False)
w = out / 'src'
w.mkdir()
rows = []
base = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base=' + str(out / 'base'), '--host_jvm_args=-Xmx1024m', '--ignore_all_rc_files']
flags = ['--jobs=2', '--worker_max_instances=MSBuildAssembly=1', '--strategy=MSBuildAssembly=worker', '--disk_cache=', '--remote_cache=', '--lockfile_mode=off']
if not a.legacy:
    flags += ['--define=rules_msbuild_stable_path_prototype=1']

def put(name, text):
    path = w / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)

for name in ['global.json', '.bazelversion']:
    shutil.copyfile(root / name, w / name)
put('MODULE.bazel', 'module(name="stable_worker_projects")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path=' + json.dumps(str(root)) + ')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",global_json="//:global.json",platforms=["linux-arm64"])\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
put('BUILD.bazel', 'exports_files(["global.json"])\n')
project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>{}</Project>'
props = '''<Project><PropertyGroup><DefineConstants>$(DefineConstants);FIRST</DefineConstants></PropertyGroup>
<Target Name="AssetMetadata" BeforeTargets="GetAssemblyAttributes"><ItemGroup>
<AssemblyAttribute Include="System.Reflection.AssemblyMetadataAttribute" Condition="'@(EmbeddedResource)' != ''">
<_Parameter1>%(EmbeddedResource.Identity)</_Parameter1><_Parameter2>%(EmbeddedResource.FullPath)</_Parameter2>
</AssemblyAttribute></ItemGroup></Target></Project>'''
c_code = 'public static class C { public const int Number = 1; public static int Value() => 1; }'
b_code = '''public static class B {
public const int Number = C.Number;
public static int Value() => C.Value();
public static string ImportValue() {
#if FIRST
return "first";
#elif OTHER
return "other";
#else
#error Missing imported constant
#endif
}
}'''
for name in ['C', 'B', 'A', 'Fan', 'Unrelated', 'Test']:
    deps = [] if name in ['C', 'Unrelated'] else ['C'] if name == 'B' else ['B'] if name in ['A', 'Fan'] else ['A']
    refs = '<ItemGroup>' + ''.join(f'<ProjectReference Include="../{dep}/{dep}.csproj" />' for dep in deps) + '</ItemGroup>'
    put(f'{name}/{name}.csproj', project.format(refs + ('<Import Project="Assets.props" />' if name == 'B' else '')))
    code = c_code if name == 'C' else b_code if name == 'B' else 'public class Unrelated {}' if name == 'Unrelated' else f'public static class {name} {{ public const int Number = B.Number; public static int Value() => B.Value(); }}'
    if name == 'Test':
        code = '''using System;
using System.IO;
using System.Linq;
using System.Reflection;
var assembly = typeof(B).Assembly;
var resources = string.Join(",", assembly.GetManifestResourceNames().Order().Select(n => n + ":" + new StreamReader(assembly.GetManifestResourceStream(n)!).ReadToEnd()));
var paths = string.Join(",", assembly.GetCustomAttributes<AssemblyMetadataAttribute>().Select(a => a.Value));
Console.WriteLine("RESULT="+A.Number+"|"+A.Value()+"|"+B.ImportValue()+"|"+resources+"|"+paths);
return A.Value() == 1 ? 0 : 1;'''
    put(f'{name}/Code.cs', code)
    rule = 'msbuild_test' if name == 'Test' else 'msbuild_library'
    extra = ',use_apphost=False' if name == 'Test' else ''
    if name in ['A', 'Fan']:
        extra += ',transitive_compile_references=' + str(a.transitive)
    if name == 'B':
        extra += ',msbuild_imports=["Assets.props"],items=[":assets"]'
    build = 'package(default_visibility=["//visibility:public"])\n' + f'load("@rules_msbuild//msbuild:defs.bzl","{rule}","msbuild_items")\n'
    if name == 'B':
        build += 'msbuild_items(name="assets",item_type="EmbeddedResource",srcs=glob(["*.txt"],allow_empty=True),metadata={"LogicalName":"asset"})\n'
    build += f'{rule}(name="{name}",project="{name}.csproj",srcs=["Code.cs"],target_framework="net10.0",deps={json.dumps(["//"+d for d in deps])},linux_worker=True{extra})\n'
    put(f'{name}/BUILD.bazel', build)
put('B/Assets.props', props)
put('B/asset.txt', 'one')

def actions(path):
    text = path.read_text().strip()
    decoder = json.JSONDecoder()
    result = []
    while text:
        row, end = decoder.raw_decode(text)
        result.append(row)
        text = text[end:].lstrip()
    return result

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def run(case, expected, compiled=None, output=None):
    execution = out / (case + '.execution.json')
    start = time.monotonic()
    command = base + ['test', '//Test', '//Fan', '//Unrelated', '--test_output=all', '--execution_log_json_file=' + str(execution)] + flags
    r = subprocess.run(command, cwd=w, capture_output=True, text=True, timeout=600)
    log = r.stdout + r.stderr
    (out / (case + '.log')).write_text(log)
    assert r.returncode == expected, (case, r.returncode, log[-8000:])
    all_actions = actions(execution)
    builds = [v for v in all_actions if v.get('mnemonic') == 'MSBuildAssembly' and not v.get('cacheHit')]
    names = sorted(v['targetLabel'].split(':')[-1] for v in builds)
    if compiled is not None:
        assert names == sorted(compiled), (case, names, compiled)
    if output is not None:
        assert output in log, (case, output, log[-4000:])
    hashes = {n: digest(w / 'bazel-bin' / n / (n+'.reference') / (n+'.dll')) for n in ['C','B','A','Fan'] if (w/'bazel-bin'/n/(n+'.reference')/(n+'.dll')).exists()}
    info = {n: json.loads((w/'bazel-bin'/n/(n+'.diagnostics')/'worker.json').read_text()) for n in names if (w/'bazel-bin'/n/(n+'.diagnostics')/'worker.json').exists()}
    row = dict(case=case, seconds=round(time.monotonic()-start,3), compiled=names, references=hashes, worker={n:{k:v.get(k) for k in ['processId','identity','projectKey','workspace']} for n,v in info.items()}, testExecuted=any(v.get('mnemonic')=='TestRunner' and not v.get('cacheHit') for v in all_actions), exitCode=r.returncode)
    if case == 'baseline':
        row['payloads'] = {n: {f: digest(w/'bazel-bin'/n/(n+'.runtime')/f) for f in [n+'.dll',n+'.pdb']} for n in ['C','B','A','Fan']}
    rows.append(row)
    (out/'report.json').write_text(json.dumps(dict(legacy=a.legacy,transitive=a.transitive,rows=rows),indent=2)+'\n')
    print(case, names, row['seconds'], flush=True)
    return row

try:
    before = run('baseline',0,['C','B','A','Fan','Unrelated','Test'],'RESULT=1|1|first|asset:one|')
    if a.expected_baseline:
        previous = json.loads(a.expected_baseline.read_text())['rows'][0]
        assert before['references'] == previous['references'], (before,previous)
        assert before['payloads'] == previous['payloads'], (before,previous)
    run('noop',0,[])
    put('C/Code.cs', c_code.replace('Value() => 1', 'Value() => 2'))
    body = run('body',3,['C'],'RESULT=1|2|first|asset:one|')
    assert body['references'] == before['references'] and body['testExecuted'], body
    put('C/Code.cs',c_code)
    run('body-revert',0,['C'])
    put('C/Code.cs', c_code.replace('public const', 'public static int Added() => 7; public const'))
    addition = run('unused-api',0,['C','B','Test'] + (['A','Fan'] if a.legacy or a.transitive else []))
    assert (addition['references']['B'] == before['references']['B']) == (not a.legacy), addition
    if not a.legacy:
        assert addition['worker']['B']['workspace'] == before['worker']['B']['workspace']
    assert addition['worker']['B']['identity'] != before['worker']['B']['identity']
    put('C/Code.cs',c_code.replace('Number = 1','Number = 2'))
    constant = run('propagated-constant',0,['C','B','A','Fan','Test'],'RESULT=2|1|first|asset:one|')
    assert all(constant['references'][n] != before['references'][n] for n in ['C','B','A','Fan'])
    if a.legacy:
        # Reproduction complete: the same unused API edit changes B's metadata.
        pass
    else:
        stamp = (w/'B/Assets.props').stat().st_mtime_ns
        put('B/Assets.props',props.replace('FIRST','OTHER'))
        os.utime(w/'B/Assets.props',ns=(stamp,stamp))
        imports = run('same-size-time-import',0,['B'],'RESULT=2|1|other|asset:one|')
        assert imports['references'] == constant['references'], imports
        put('B/asset.txt','two')
        resource = run('resource-content',0,['B'],'RESULT=2|1|other|asset:two|')
        assert resource['references'] == imports['references'] and resource['testExecuted'], resource
        (w/'B/asset.txt').unlink()
        removed = run('resource-removed',0,['B','A','Fan','Test'],'RESULT=2|1|other||')
        assert removed['references']['B'] != resource['references']['B']
        put('B/asset.txt','two')
        added = run('resource-readded',0,['B','A','Fan','Test'],'RESULT=2|1|other|asset:two|')
        assert added['references']['B'] == resource['references']['B']
        # Rename removes the old declared input and changes the FullPath attribute.
        (w/'B/asset.txt').rename(w/'B/other.txt')
        renamed = run('resource-rename',0,['B','A','Fan','Test'],'RESULT=2|1|other|asset:two|')
        assert renamed['references']['B'] != resource['references']['B']
        text = (out/'resource-rename.log').read_text()
        assert '/other.txt' in text and '/asset.txt' not in text, text[-4000:]
        put('B/Assets.props','<Project><invalid></Project>')
        run('invalid-xml',1,['B'])
        put('B/Assets.props',props)
        recovered = run('xml-recovered',0,['B'],'RESULT=2|1|first|asset:two|')
        assert recovered['references']['B'] == renamed['references']['B']
        # Missing dependency type cannot be hidden by pruning compiler inputs.
        put('C/Code.cs',c_code + ' public class PublicType {}')
        put('B/Code.cs',b_code + ' public class Exposed : PublicType {}')
        run('exposed-producer',0,['C','B','A','Fan','Test'])
        put('A/Code.cs','public static class A { public const int Number = B.Number; public static int Value() => B.Value(); public static object Make() => new Exposed(); }')
        # Inheritance requires the transitive public base type from C.
        put('A/Code.cs',(w/'A/Code.cs').read_text() + ' public class Consumer : Exposed {}')
        if a.transitive:
            run('exposed-consumer',0,['A','Test'])
        else:
            run('missing-required-reference',1,['A'])
            assert 'CS0012' in (out/'missing-required-reference.log').read_text()
            build=(w/'A/BUILD.bazel').read_text().replace('deps=["//B"]','deps=["//B","//C"]')
            put('A/BUILD.bazel',build)
            put('A/A.csproj',(w/'A/A.csproj').read_text().replace('</ItemGroup>','<ProjectReference Include="../C/C.csproj" /></ItemGroup>'))
            run('explicit-reference-repair',0,['A','Test'])
        # Mutable task-loading state is outside the prototype; reject, don't guess.
        put('B/Assets.props',props.replace('<Project>','<Project><UsingTask TaskName="Unknown" AssemblyFile="missing.dll"/>',1))
        run('custom-task-rejected',1,['B'])
        assert 'does not support custom SDKs or task registrations' in (out/'custom-task-rejected.log').read_text()
        put('B/Assets.props',props)
        run('task-rejection-recovered',0,['B'])
        pids = {value['processId'] for row in rows if row['exitCode'] in [0,3] for value in row['worker'].values()}
        assert len(pids) == 1, pids
        # Every reference path in compiler diagnostics uses the artifact digest.
        compiler_log=(w/'bazel-bin/B/B.diagnostics/compiler.log').read_text()
        assert '/__rules_msbuild/in/artifacts/' in compiler_log, compiler_log[-4000:]
finally:
    subprocess.run(base+['shutdown'],cwd=w,check=True)
