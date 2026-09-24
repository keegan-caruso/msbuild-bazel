"""Declare an installed native runtime with only Immutable replaced by its Bazel output.

This is an execution control, not a source-built CoreCLR qualification. The startup
hook proves the actual testhost loads the declared replacement assembly.
"""
import json
from pathlib import Path
import shutil
import sys

workspace = Path(sys.argv[1]).resolve()
host = workspace / 'runtime'
frameworks = list((host/'shared/Microsoft.NETCore.App').iterdir())
assert len(frameworks) == 1 and frameworks[0].name == "10.0.11", frameworks
framework = frameworks[0].relative_to(host).as_posix()
immutable = 'src_libraries_System.Collections.Immutable_src_System.Collections.Immutable_net10.0'
probe = workspace / 'load_probe'
probe.mkdir(exist_ok=False)
shutil.copyfile(Path(__file__).with_name('LoadProbe.cs.txt'), probe/'StartupHook.cs')
(probe/'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>\n')
(probe/'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl", "msbuild_library")
msbuild_library(name="probe",project="Probe.csproj",srcs=["StartupHook.cs"],assembly_name="Probe",target_framework="net10.0",linux_worker=True,visibility=["//runtime:__pkg__"])
''')
wrapper = host/'host.sh'
wrapper.write_text('''#!/bin/sh
set -eu
ulimit -c 0
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
export DOTNET_ROOT="$root"
export DOTNET_STARTUP_HOOKS="$root/probe/Probe.dll"
export QUALIFICATION_IMMUTABLE="$root/FRAMEWORK/System.Collections.Immutable.dll"
exec "$root/dotnet" "$@"
'''.replace('FRAMEWORK',framework))
wrapper.chmod(0o755)
# Omit the installed Immutable DLL entirely from the declared host tree.
paths = {str(p.relative_to(host)): str(p.relative_to(host)) for p in host.rglob('*')
         if p.is_file() and p.name != 'BUILD.bazel' and p != frameworks[0]/'System.Collections.Immutable.dll'}
paths['//upstream:'+immutable] = framework
paths['//load_probe:probe'] = 'probe'
(host/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_layout","msbuild_runtime")\nmsbuild_layout(name="tree",paths='+json.dumps(paths)+')\nmsbuild_runtime(name="host",layout=":tree",entry_point="host.sh",visibility=["//visibility:public"])\n')
build = workspace/'upstream/BUILD.bazel'
lines = build.read_text().splitlines()
for i,line in enumerate(lines):
    if line.startswith('msbuild_library(') and ('name="'+immutable+'"' in line or "name='"+immutable+"'" in line):
        lines[i] = line[:-1]+',visibility=["//runtime:__pkg__","//smoke:__pkg__"])'
build.write_text('\n'.join(lines)+'\n')
