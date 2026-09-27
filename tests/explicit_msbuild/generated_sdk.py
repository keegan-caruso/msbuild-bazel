"""Prove action-produced SDK files/directories feed runner, compile and runtime actions.

By default this repackages a verified downloaded SDK. --archive instead consumes
a separately built SDK archive. Neither mode builds the SDK source graph.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('directory', type=Path)
p.add_argument('--worker', action='store_true')
p.add_argument('--archive', type=Path, help='Previously source-built SDK tar.gz to qualify')
p.add_argument('--sdk-version', default='10.0.400')
p.add_argument('--runtime-version', default='10.0.11')
a = p.parse_args()
root = Path(__file__).resolve().parents[2]
w = a.directory.resolve()/'source'
w.mkdir(parents=True, exist_ok=False)
rid = ('osx' if platform.system() == 'Darwin' else 'linux') + ('-arm64' if platform.machine() in ['arm64', 'aarch64'] else '-x64')
archive_hash = None
if a.archive:
    archive_hash = hashlib.sha256(a.archive.read_bytes()).hexdigest()
    shutil.copyfile(a.archive, w/'source-sdk.tar.gz')
bootstrap = '' if a.archive else '''dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")
dotnet.sdk(name="bootstrap",version="10.0.400",platforms=[%s])
use_repo(dotnet,"bootstrap")
''' % json.dumps(rid)
(w/'MODULE.bazel').write_text('''module(name="generated_sdk_fixture")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path=%s)
''' % json.dumps(str(root)) + bootstrap +
    'register_toolchains("//:produced_registered","//:produced_runtime_registered")\n')
(w/'producer.bzl').write_text('''load("@rules_msbuild//msbuild:defs.bzl", "MSBuildRuntimeInfo")
def _produce(ctx):
    dotnet = ctx.actions.declare_file(ctx.label.name + "/dotnet")
    directories = [ctx.actions.declare_directory(ctx.label.name + "/" + name) for name in ["host", "shared", "sdk", "packs", "sdk-manifests", "templates", "library-packs", "metadata"]]
    extras = [ctx.actions.declare_file(ctx.label.name + "/" + name) for name in ["LICENSE.txt", "ThirdPartyNotices.txt", "dnx"]] if ctx.file.archive else []
    if ctx.file.archive:
        ctx.actions.run_shell(inputs = [ctx.file.archive], outputs = [dotnet] + directories + extras,
            arguments = [ctx.file.archive.path, dotnet.path] + [d.path for d in directories],
            command = """set -eu
archive="$1"; dotnet="$2"; shift 2
root="${dotnet%/*}"
mkdir -p "$root"
tar -xzf "$archive" -C "$root"
for output in "$@"; do mkdir -p "$output"; done
""", mnemonic = "SourceSdkArchiveProducer")
    else:
        host = ctx.attr.source[MSBuildRuntimeInfo]
        ctx.actions.run_shell(inputs = host.files, outputs = [dotnet] + directories, arguments = [host.directory.path, dotnet.path] + [d.path for d in directories], command = """set -eu
source="$1"; dotnet="$2"; shift 2
cp -pL "$source/dotnet" "$dotnet"
for output in "$@"; do
    mkdir -p "$output"
    part="${output##*/}"
    if test -d "$source/$part"; then cp -RL "$source/$part/." "$output/"; fi
done
""", mnemonic = "SyntheticSdkProducer")
    return [DefaultInfo(files = depset([dotnet] + directories + extras)), OutputGroupInfo(dotnet = depset([dotnet]))]
produce = rule(implementation = _produce, attrs = {"source": attr.label(providers = [MSBuildRuntimeInfo]), "archive": attr.label(allow_single_file = [".tar.gz"])})
''')
(w/'BUILD.bazel').write_text('''load(":producer.bzl","produce")
load("@rules_msbuild//msbuild:sdk.bzl","msbuild_sdk")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_library","msbuild_test")
produce(name="artifacts",%s)
filegroup(name="dotnet",srcs=[":artifacts"],output_group="dotnet")
msbuild_sdk(name="produced",dotnet=":dotnet",files=[":artifacts"],sdk_version=%s,runtime_version=%s,runtime_identifier=%s)
msbuild_library(name="lib",project="Lib.csproj",srcs=["Lib.cs"],target_framework="net10.0",linux_worker=%s)
msbuild_test(name="test",project="App.csproj",srcs=["App.cs"],deps=[":lib"],target_framework="net10.0",use_apphost=False,linux_worker=%s)
''' % ('archive="source-sdk.tar.gz"' if a.archive else 'source="@bootstrap//:sdk_host"', json.dumps(a.sdk_version), json.dumps(a.runtime_version), json.dumps(rid), a.worker, a.worker))
(w/'Lib.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
(w/'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><ProjectReference Include="Lib.csproj" /></ItemGroup></Project>')
(w/'Lib.cs').write_text('public static class Lib { public static int Value() => 1; }')
(w/'App.cs').write_text('System.Console.WriteLine("GENERATED_SDK="+System.Environment.Version); return Lib.Value()==1 ? 0 : 1;')
base = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base='+str(a.directory.resolve()/'base'), '--ignore_all_rc_files']
reports = []
try:
    for case, flags, expected in [('build', [], 0), ('offline', ['--nofetch'], 0), ('body-edit', [], 3), ('api-edit', [], 1)]:
        if case == 'body-edit':
            (w/'Lib.cs').write_text('public static class Lib { public static int Value() => 2; }')
        if case == 'api-edit':
            (w/'Lib.cs').write_text('public static class Lib { public static int Value(int required) => required; }')
        result = subprocess.run(base+['test', '//:test', '--jobs=2', '--test_output=all', '--lockfile_mode=off', *(['--strategy=MSBuildAssembly=worker', '--worker_max_instances=MSBuildAssembly=1'] if a.worker else []), *flags], cwd=w, capture_output=True, text=True)
        (a.directory/(case+'.log')).write_text(result.stdout+result.stderr)
        assert result.returncode == expected, result.stdout+result.stderr
        if case in ['build', 'offline']:
            assert 'GENERATED_SDK='+a.runtime_version.split('-')[0] in result.stdout+result.stderr
        reports.append(dict(case=case, exitCode=result.returncode, sdkVersion=a.sdk_version, runtimeVersion=a.runtime_version, archiveSha256=archive_hash))
        print(case, result.returncode, flush=True)
    (a.directory/'report.json').write_text(json.dumps(reports, indent=2)+'\n')
finally:
    subprocess.run(base+['shutdown'], cwd=w, check=True)
