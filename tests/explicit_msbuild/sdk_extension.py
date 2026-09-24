"""Fresh SDK/global.json acquisition builds the runner and supplies app runtimes."""
import argparse
import json
import os
from pathlib import Path
import platform
import subprocess

ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('directory',type=Path)
a=p.parse_args()
a.directory.mkdir(parents=True)
w=a.directory.resolve()/'source';w.mkdir()
bazel=os.environ['RULES_MSBUILD_BAZEL']
rid=('osx' if platform.system()=='Darwin' else 'linux')+('-arm64' if platform.machine() in ['arm64','aarch64'] else '-x64')
module=f'''module(name="sdk_extension_fixture")
bazel_dep(name="rules_msbuild",version="0.0.0")
bazel_dep(name="platforms",version="1.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})
dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")
dotnet.sdk(name="dotnet",global_json="//:global.json",platforms=[{json.dumps(rid)}])
dotnet.runtime(name="older",version="10.0.0",platforms=[{json.dumps(rid)}])
use_repo(dotnet,"dotnet","older")
register_toolchains("@dotnet//:all")
'''
(w/'MODULE.bazel').write_text(module)
(w/'global.json').write_text('{ // shared with the dotnet CLI\n "sdk": { "version": "10.0.400", "rollForward": "disable", "allowPrerelease": false } }')
(w/'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
(w/'Program.cs').write_text('System.Console.WriteLine("RUNTIME="+System.Environment.Version); System.Console.WriteLine(typeof(object).Assembly.Location); return 0;')
(w/'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl","msbuild_binary","msbuild_test")
exports_files(["global.json"])
platform(name="unsupported",constraint_values=["@platforms//os:freebsd","@platforms//cpu:aarch64"])
msbuild_binary(name="app",project="App.csproj",srcs=["Program.cs"],target_framework="net10.0",use_apphost=False)
msbuild_test(name="test",project="App.csproj",srcs=["Program.cs"],target_framework="net10.0",use_apphost=False)
msbuild_test(name="override",project="App.csproj",srcs=["Program.cs"],target_framework="net10.0",use_apphost=False,runtime_host="@older//:runtime")
''')
base=[bazel,'--output_base='+str(a.directory.resolve()/'base'),'--ignore_all_rc_files']
records=[]
def run(case,command='test',target=':test',extra=(),failure=None,expected='10.0.11'):
    result=subprocess.run(base+[command,target,'--jobs=2','--lockfile_mode=off',*(['--test_output=all'] if command=='test' else []),*extra],cwd=w,text=True,capture_output=True)
    (a.directory/(case+'.log')).write_text(result.stdout+result.stderr)
    if failure:
        assert result.returncode!=0 and failure in result.stdout+result.stderr,result.stdout+result.stderr
    else:
        assert result.returncode==0,result.stdout+result.stderr
        assert 'RUNTIME='+expected in result.stdout+result.stderr,result.stdout+result.stderr
    records.append(dict(case=case,exitCode=result.returncode))
try:
    run('global-json')
    run('binary','run',':app')
    run('offline',extra=['--nofetch'])
    run('runtime-override',target=':override',expected='10.0.0')
    (w/'MODULE.bazel').write_text(module.replace('global_json="//:global.json"','version="10.0.400"'))
    run('explicit-version')
    run('unsupported-target',command='build',target=':app',extra=['--platforms=//:unsupported'],failure='No SDK runtime matches the target platform')
    (w/'MODULE.bazel').write_text(module)
    (w/'global.json').write_text('{"sdk":{"version":"10.0.401","rollForward":"disable"}}')
    run('sdk-version-change',expected='10.0.12')
    (w/'global.json').write_text('{"sdk":{"version":"10.0.400","rollForward":"latestFeature"}}')
    run('unsupported-policy',failure='rollForward must be disable or patch')
    (w/'global.json').write_text('{"sdk":{"version":"not-pinned"}}')
    run('changed-pin',failure='Unknown pinned SDK version')
    (a.directory/'report.json').write_text(json.dumps(records,indent=2)+'\n')
    print(json.dumps(records,indent=2))
finally:
    subprocess.run(base+['shutdown'],cwd=w,check=True)
