"""Downloaded and generated runtime hosts share launch and invalidation behavior."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess

ROOT = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('directory', type=Path)
a = p.parse_args()
a.directory.mkdir(parents=True)
w = a.directory.resolve() / 'source'
w.mkdir()
bazel = os.environ['RULES_MSBUILD_BAZEL']
sdk = os.environ['RULES_MSBUILD_DOTNET_ROOT']
version = subprocess.check_output([bazel, '--version'], text=True).strip()
assert version == 'bazel ' + os.environ['USE_BAZEL_VERSION'], version
rid = ('osx' if platform.system() == 'Darwin' else 'linux') + ('-arm64' if platform.machine() in ('arm64', 'aarch64') else '-x64')
(w/'MODULE.bazel').write_text(f'''module(name="runtime_download_test")
bazel_dep(name="rules_msbuild", version="0.0.0")
local_path_override(module_name="rules_msbuild", path={json.dumps(str(ROOT))})
dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl", "dotnet")
dotnet.runtime(name="net10", version="10.0.0", platforms=[{json.dumps(rid)}])
use_repo(dotnet, "net10")
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl", "local_dotnet_sdk")
sdk(name="sdk", path={json.dumps(sdk)}, include_runtime_closure=False)
register_toolchains("//:registered")
''')
(w/'adapt.bzl').write_text('''load("@rules_msbuild//msbuild:defs.bzl", "MSBuildRuntimeInfo", "MSBuildLayoutInfo")
def _tree(ctx):
    directory=ctx.attr.runtime[MSBuildRuntimeInfo].directory
    return [DefaultInfo(files=depset([directory])), MSBuildLayoutInfo(directory=directory)]
runtime_tree=rule(implementation=_tree, attrs={"runtime":attr.label(providers=[MSBuildRuntimeInfo])})
def _host(ctx):
    host=ctx.actions.declare_file(ctx.label.name+".sh")
    ctx.actions.write(host, ctx.attr.script, is_executable=True)
    return [DefaultInfo(files=depset([host]))]
generated_host=rule(implementation=_host, attrs={"script":attr.string()})
''')
header='''load("@rules_msbuild//msbuild:toolchain.bzl", "msbuild_toolchain")
load("@rules_msbuild//msbuild:defs.bzl", "msbuild_layout", "msbuild_runtime", "msbuild_test")
load(":adapt.bzl", "runtime_tree", "generated_host")
msbuild_toolchain(name="implementation",dotnet="@sdk//:sdk/dotnet",sdk="@sdk//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@sdk//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
runtime_tree(name="downloaded_tree",runtime="@net10//:runtime")
msbuild_layout(name="generated_tree",paths={":downloaded_tree":".",":wrapper":"host.sh"})
msbuild_runtime(name="generated_runtime",layout=":generated_tree",entry_point="host.sh",env={"RUNTIME_MARKER":"declared"},version="10.0.0")
msbuild_test(name="app",project="App.csproj",srcs=["Program.cs"],target_framework="net10.0",use_apphost=False,runtime_host=":generated_runtime")
msbuild_test(name="downloaded",project="App.csproj",srcs=["Program.cs"],target_framework="net10.0",use_apphost=False,runtime_host="@net10//:runtime")
'''
wrapper='#!/bin/sh\ntest "$RUNTIME_MARKER" = declared || exit 31\nexec "$(dirname "$0")/dotnet" "$@"\n'
def build_file(script):
    (w/'BUILD.bazel').write_text(header+'generated_host(name="wrapper",script='+json.dumps(script)+')\n')
build_file(wrapper)
(w/'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
(w/'Program.cs').write_text('System.Console.WriteLine(typeof(object).Assembly.Location); return System.Environment.Version.ToString() == "10.0.0" ? 0 : 17;')
records=[]
base=[bazel,'--output_base='+str(a.directory.resolve()/'base'),'--ignore_all_rc_files']
def run(case, target=':app', failure=False, no_compile=False, offline=False):
    execution=a.directory.resolve()/(case+'.json')
    cmd=base+['test',target,'--test_output=all','--jobs=2','--lockfile_mode=off','--execution_log_json_file='+str(execution)]
    if offline:cmd+=['--nofetch']
    result=subprocess.run(cmd,cwd=w,text=True,capture_output=True)
    (a.directory/(case+'.log')).write_text(result.stdout+result.stderr)
    assert (result.returncode!=0)==failure,result.stdout+result.stderr
    text=execution.read_text().strip(); rows=[];decoder=json.JSONDecoder()
    while text:
        row,end=decoder.raw_decode(text);rows.append(row);text=text[end:].lstrip()
    compiled=[r for r in rows if r.get('mnemonic')=='MSBuildAssembly' and not r.get('cacheHit')]
    tests=[r for r in rows if r.get('mnemonic')=='TestRunner' and not r.get('cacheHit')]
    if no_compile:assert not compiled,case
    records.append(dict(case=case,compiled=len(compiled),tests=len(tests),exitCode=result.returncode))
    return tests
try:
    run('downloaded',':downloaded')
    run('generated')
    assert not run('noop',no_compile=True)
    build_file(wrapper+'# changed host input\n')
    assert run('runtime-edit',no_compile=True)
    build_file('#!/bin/sh\nexit 19\n')
    assert run('runtime-failure',failure=True,no_compile=True)
    build_file(wrapper)
    run('restored-offline',no_compile=True,offline=True)
    (a.directory/'results.json').write_text(json.dumps(dict(bazel=version,platform=rid,cases=records),indent=2)+'\n')
    print(json.dumps(records,indent=2))
finally:
    subprocess.run(base+['shutdown'],cwd=w,check=True)
