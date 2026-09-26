"""Use a declared installed runtime with only source-built Pipelines substituted.

The startup hook verifies actual testhost assembly loads. This focused generator
qualification does not repeat the earlier source-only CoreCLR host qualification.
"""
import json
from pathlib import Path
import sys

root=Path(sys.argv[1]).resolve();rules=Path(__file__).resolve().parents[3]
host=root/'runtime';framework=next((host/'shared/Microsoft.NETCore.App').iterdir()).relative_to(host).as_posix()
probe=root/'load_probe';probe.mkdir()
source=(rules/'tests/explicit_msbuild/runtime/LoadProbe.cs.txt').read_text().replace('System.Collections.Immutable','System.IO.Pipelines').replace('QUALIFICATION_IMMUTABLE','QUALIFICATION_PIPELINES').replace('loaded-immutable','loaded-pipelines').replace('Immutable','Pipelines')
(probe/'StartupHook.cs').write_text(source)
(probe/'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
(probe/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_library")\nmsbuild_library(name="probe",project="Probe.csproj",srcs=["StartupHook.cs"],assembly_name="Probe",target_framework="net10.0",visibility=["//runtime:__pkg__"])\n')
(host/'host.sh').write_text('#!/bin/sh\nset -eu\nulimit -c 0\nroot=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\nexport DOTNET_ROOT="$root"\nexport DOTNET_STARTUP_HOOKS="$root/probe/Probe.dll"\nexport QUALIFICATION_PIPELINES="$root/'+framework+'/System.IO.Pipelines.dll"\nexec "$root/dotnet" "$@"\n')
(host/'host.sh').chmod(0o755)
paths={p.relative_to(host).as_posix():p.relative_to(host).as_posix() for p in host.rglob('*') if p.is_file() and p.name!='BUILD.bazel' and p.name!='System.IO.Pipelines.dll'}
paths['//:src_libraries_System.IO.Pipelines_src_System.IO.Pipelines_net10_0']=framework
paths['//load_probe:probe']='probe'
(host/'BUILD.bazel').write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_layout","msbuild_runtime")\nmsbuild_layout(name="tree",paths='+json.dumps(paths)+')\nmsbuild_runtime(name="host",layout=":tree",entry_point="host.sh",visibility=["//visibility:public"])\n')
p=root/'BUILD.bazel';p.write_text('package(default_visibility=["//visibility:public"])\nload(":projects.generated.bzl","app_projects")\n'+p.read_text()+'\napp_projects()\n')
