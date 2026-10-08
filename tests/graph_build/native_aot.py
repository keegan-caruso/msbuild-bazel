"""Linux ARM64 graph Publish with declared AOT packages and native tool bindings.

Producer and consumer phases must run in independent containers. Recovery disables
Bazel action caches and executes the recovered ELF through a native Bazel test.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from fixture_sdk import sdk_declarations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('inputs', type=Path, help='Verified .nupkg/.deb acquisition directory')
    parser.add_argument('directory', type=Path, help='New disposable qualification directory')
    parser.add_argument('--phase', choices=['producer', 'consumer'], required=True)
    parser.add_argument('--seed-report', type=Path)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--acquire', action='store_true', help='Acquire pinned archives into a new inputs directory')
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux' and os.uname().machine == 'aarch64'
    assert (args.phase == 'consumer') == bool(args.seed_report)
    folder = args.directory.resolve()
    root = folder / 'workspace'
    root.mkdir(parents=True, exist_ok=False)
    here = Path(__file__).with_suffix('')
    packages = json.loads((here / 'packages.json').read_text())
    native = json.loads((here / 'native-packages.json').read_text())['packages']
    if args.acquire:
        args.inputs.mkdir(parents=True, exist_ok=False)
        rows = [(identity+'.'+packages['version']+'.nupkg',
                 'https://api.nuget.org/v3-flatcontainer/'+identity+'/'+packages['version']+'/'+identity+'.'+packages['version']+'.nupkg',item['sha256'])
                for identity,item in packages['packages'].items()]
        rows += [(item['name']+'.deb',item['url'],item['sha256']) for item in native]
        def download(row):
            name,url,digest=row
            with urlopen(url,timeout=120) as response:
                data=response.read()
            assert hashlib.sha256(data).hexdigest()==digest,name
            (args.inputs/name).write_bytes(data)
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(download,rows))
    def put(name, text):
        (root / name).write_text(text)
    paths = []
    lines = ['load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph","msbuild_graph_runner","msbuild_graph_output","msbuild_nuget_package","msbuild_package_lock","msbuild_native_toolchain_packages","msbuild_layout","msbuild_native_tool","msbuild_file_binding")',
             'load("@rules_shell//shell:sh_test.bzl","sh_test")']
    def acquire(name, digest):
        source = args.inputs / name
        assert hashlib.sha256(source.read_bytes()).hexdigest() == digest, name
        shutil.copyfile(source, root / name)
    for index, (identity, item) in enumerate(packages['packages'].items()):
        name = identity + '.' + packages['version'] + '.nupkg'
        acquire(name, item['sha256'])
        label = 'p' + str(index)
        paths.append(':' + label)
        lines.append('msbuild_nuget_package(name='+json.dumps(label)+',package_id='+json.dumps(identity)+',version='+json.dumps(packages['version'])+',archive='+json.dumps(name)+',archive_sha256='+json.dumps(item['sha256'])+',content_hash='+json.dumps(item['contentHash'])+')')
    debs = {}
    for package in native:
        name = package['name'] + '.deb'
        acquire(name, package['sha256'])
        debs[name] = package['sha256']
    shutil.copyfile(here / 'native-files.manifest', root / 'native-files.manifest')
    put('clang', '''#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export LD_LIBRARY_PATH="$root/usr/lib/aarch64-linux-gnu:$root/usr/lib/llvm-14/lib"
exec "$root/usr/bin/clang" --sysroot="$root" --gcc-toolchain="$root/usr" -B"$root/usr/bin" -L"$root/usr/lib/aarch64-linux-gnu" "$@"
''')
    put('objcopy', '''#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export LD_LIBRARY_PATH="$root/usr/lib/aarch64-linux-gnu:$root/usr/lib/llvm-14/lib"
exec "$root/usr/bin/llvm-objcopy" "$@"
''')
    for name in ['clang', 'objcopy']:
        (root / name).chmod(0o755)
    put('MODULE.bazel', 'module(name="graph_native_aot")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(ROOT))+')\nbazel_dep(name="rules_shell",version="0.6.1")\n'+sdk_declarations())
    put('Hello.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><RuntimeIdentifier>linux-arm64</RuntimeIdentifier><OutputType>Exe</OutputType><PublishAot>true</PublishAot><SelfContained>true</SelfContained><PublishDir>bin/publish/</PublishDir></PropertyGroup></Project>')
    original = 'System.Console.WriteLine("GRAPH_AOT_INITIAL");\n'
    put('Program.cs', original)
    put('contract.json', json.dumps(dict(Version=1, Entry='Hello.csproj', SdkVersion='10.0.400', Properties={'Configuration':'Release'}, SharedInputs=[], ToolProperties={'CppCompilerAndLinker':'.graph-tools/0/clang','ObjCopyName':'.graph-tools/1/objcopy'}, Projects={'Hello.csproj':dict(Inputs=['Hello.csproj','Program.cs'],OutputDirectories=['bin/Release/net10.0/linux-arm64','obj/Release/net10.0/linux-arm64','bin/publish'])})))
    lines += ['msbuild_package_lock(name="packages",packages='+json.dumps(paths)+')',
              'msbuild_native_toolchain_packages(name="native",packages='+json.dumps(debs)+',manifest="native-files.manifest")',
              'msbuild_layout(name="tools",paths={":native":".","clang":"clang","objcopy":"objcopy"})',
              'msbuild_native_tool(name="clang_tool",layout=":tools",entry_point="clang")',
              'msbuild_native_tool(name="objcopy_tool",layout=":tools",entry_point="objcopy")',
              'msbuild_file_binding(name="clang_binding",tool=":clang_tool",property_name="CppCompilerAndLinker")',
              'msbuild_file_binding(name="objcopy_binding",tool=":objcopy_tool",property_name="ObjCopyName")',
              'msbuild_graph_runner(name="runner")',
              'msbuild_graph(name="graph",runner=":runner",contract="contract.json",srcs=["Hello.csproj","Program.cs"],bindings=[":clang_binding",":objcopy_binding"],package_lock=":packages",target="Publish",linux_stable_paths=True,linux_worker=True)',
              'msbuild_graph_output(name="binary",graph=":graph",path="bin/publish/Hello")',
              'sh_test(name="run",srcs=["run.sh"],data=[":binary"],args=["$(rootpath :binary)","GRAPH_AOT_INITIAL"])']
    build = '\n'.join(lines)+'\n'
    put('BUILD.bazel', build)
    put('run.sh', '''#!/usr/bin/env bash
set -euo pipefail
binary="$TEST_SRCDIR/$TEST_WORKSPACE/$1"
test "$(od -An -tx1 -N4 "$binary" | tr -d ' \\n')" = 7f454c46
test "$($binary)" = "$2"
''')
    (root / 'run.sh').chmod(0o755)
    bazel = [str(ROOT / 'scripts/bazel-launcher.sh'), '--output_base='+str(folder/'base'), '--ignore_all_rc_files']
    rows = []
    def run(case, hits, success=True):
        command = bazel + ['test','//:run','--jobs=2','--lockfile_mode=off','--strategy=MSBuildGraph=worker','--worker_sandboxing','--disk_cache=','--remote_cache=','--nocache_test_results','--test_output=all','--action_env=RULES_MSBUILD_PROJECT_CACHE_URL='+args.cache,'--build_event_json_file='+str(folder/(case+'.bep'))]
        with (folder/(case+'.log')).open('w') as log:
            result = subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=900)
        assert (result.returncode == 0) == success, folder/(case+'.log')
        if success:
            report = json.loads((root/'bazel-bin/graph.graph/report.json').read_text())
            assert (report['hits'],report['misses']) == (hits,1-hits), report
            binary = root/'bazel-bin/binary/Hello'
            data = binary.read_bytes()
            assert data[:4] == b'\x7fELF' and int.from_bytes(data[18:20],'little') == 183
            # Ensure this was a real graph execution and a real test execution.
            events = [json.loads(l) for l in (folder/(case+'.bep')).read_text().splitlines()]
            actions = next(e['buildMetrics']['actionSummary'] for e in events if 'buildMetrics' in e)
            assert sum(int(r.get('actionsExecuted',0)) for r in actions.get('actionData',[]) if r['mnemonic']=='MSBuildGraph') == 1
            assert any(e.get('testResult',{}).get('status')=='PASSED' and not e['testResult'].get('cachedLocally',False) for e in events)
            row = {'case':case,'hits':hits,'misses':1-hits,'sha256':hashlib.sha256(data).hexdigest(),'output':subprocess.check_output([binary],text=True).strip()}
            if args.phase == 'consumer':
                assert row['sha256'] == json.loads(args.seed_report.read_text())['rows'][0]['sha256']
        else:
            assert 'Microsoft.DotNet.ILCompiler' in (folder/(case+'.log')).read_text()
            row = {'case':case,'missingCompilerRejected':True}
        rows.append(row)
        (folder/'report.json').write_text(json.dumps({'platform':'linux-arm64','sdk':'10.0.400','bazel':os.environ.get('USE_BAZEL_VERSION','9.3.0'),'rows':rows},indent=2)+'\n')
        print(json.dumps(row),flush=True)
    try:
        run(args.phase, 0 if args.phase=='producer' else 1)
        if args.phase == 'producer':
            put('Program.cs',original.replace('INITIAL','EDIT'))
            put('BUILD.bazel',build.replace('"GRAPH_AOT_INITIAL"','"GRAPH_AOT_EDIT"'))
            run('body-edit',0)
            assert rows[0]['sha256'] != rows[1]['sha256']
            compiler = next(i for i,name in enumerate(packages['packages']) if name=='microsoft.dotnet.ilcompiler')
            put('BUILD.bazel',(root/'BUILD.bazel').read_text().replace(json.dumps(paths),json.dumps([p for p in paths if p!=':p'+str(compiler)])))
            run('missing-compiler',0,success=False)
    finally:
        subprocess.run(bazel+['shutdown'],cwd=root,check=True)


if __name__ == '__main__':
    main()
