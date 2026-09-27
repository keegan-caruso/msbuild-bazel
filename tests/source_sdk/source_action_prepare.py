"""Prepare declared inputs for a coarse, offline upstream SDK source-build action.

Qualification tooling only. The SDK build is one Bazel action here; this does not
claim incremental component scheduling. Input archives retain separate source,
bootstrap and native-tool identities.
"""
import argparse
import io
import json
from pathlib import Path
import platform
import posixpath
import shutil
import subprocess
import tarfile

from inventory import digest

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('source_archive', type=Path)
p.add_argument('prepared_baseline', type=Path)
p.add_argument('directory', type=Path)
a = p.parse_args()
assert platform.system() == 'Linux' and platform.machine() == 'aarch64'
here = Path(__file__).resolve().parent
rules = here.parents[1]
pin = json.loads((here / 'pin.json').read_text())
assert digest(a.source_archive) == pin['sourceArchive']['sha256']
w = a.directory.resolve()
w.mkdir(parents=True, exist_ok=False)


def normalize(entry):
    entry.uid = entry.gid = entry.mtime = 0
    entry.uname = entry.gname = ''
    if entry.issym() and entry.linkname.startswith('/'):
        entry.linkname = posixpath.relpath(entry.linkname, '/' + posixpath.dirname(entry.name))
    return entry


with tarfile.open(w / 'native.tar', 'w') as archive:
    for name in ['usr', 'bin', 'lib', 'sbin', 'etc/alternatives', 'etc/ld.so.conf',
                 'etc/ld.so.conf.d', 'etc/ld.so.cache', 'etc/os-release', 'etc/ssl',
                 'etc/passwd', 'etc/group', 'etc/nsswitch.conf']:
        archive.add('/' + name, arcname=name, filter=normalize)
    for name in ['source', 'proc', 'dev', 'tmp']:
        entry = tarfile.TarInfo(name)
        entry.type, entry.mode = tarfile.DIRTYPE, 0o755
        archive.addfile(entry)

baseline = a.prepared_baseline.resolve()
bootstrap_archive = baseline / 'prereqs/packages/archive/Private.SourceBuilt.Artifacts.Bootstrap.tar.gz'
assert bootstrap_archive.is_file()
with tarfile.open(w / 'bootstrap.tar', 'w') as archive:
    archive.add(baseline / '.dotnet', arcname='.dotnet', filter=normalize)
    archive.add(bootstrap_archive, arcname='prereqs/packages/archive/Private.SourceBuilt.Artifacts.Bootstrap.tar.gz', filter=normalize)

script = '''set -euo pipefail
export DOTNET_PROCESSOR_COUNT=2 DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_GENERATE_ASPNET_CERTIFICATE=false
patch -p1 < identitymodel.patch
./prep-source-build.sh --no-sdk --no-bootstrap --no-artifacts --no-prebuilts > preparation.log 2>&1 || { tail -100 preparation.log; exit 1; }
/usr/bin/time -v -o build.time ./build.sh -sb --clean-while-building --configuration Release --arch arm64 --official-build-id 20251023.11 --branding rtm --source-repository https://github.com/dotnet/dotnet --source-version b0f34d51fccc69fd334253924abd8d6853fad7aa /p:BuildInParallel=false > build.log 2>&1 || { tail -120 build.log; exit 1; }
mapfile -t archives < <(find artifacts/assets/Release/Sdk -name 'dotnet-sdk-*.tar.gz')
test "${#archives[@]}" = 1
mkdir result
cp "${archives[0]}" result/sdk.tar.gz
artifacts/obj/extracted-dotnet-sdk/dotnet --info > sdk-info.txt
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -cf result.tar preparation.log build.log build.time sdk-info.txt artifacts/log
'''
with tarfile.open(a.source_archive, 'r|gz') as original, tarfile.open(w / 'sources.tar', 'w') as archive:
    for entry in original:
        parts = entry.name.split('/', 1)
        if len(parts) < 2 or not parts[1]:
            continue
        entry.name = parts[1]
        if entry.islnk():
            entry.linkname = entry.linkname.split('/', 1)[1]
        data = original.extractfile(entry) if entry.isfile() else None
        archive.addfile(normalize(entry), data)
    for name, data in [('build-native.sh', script.encode()), ('identitymodel.patch', (here / 'patches/identitymodel-file-version.patch').read_bytes())]:
        entry = tarfile.TarInfo(name)
        entry.size, entry.mode = len(data), 0o644
        archive.addfile(entry, io.BytesIO(data))
shutil.copy2('/usr/bin/bwrap', w / 'bwrap')
shutil.copyfile(here / 'source_action.bzl', w / 'source_action.bzl')
shutil.copyfile(rules / 'tests/explicit_msbuild/runtime/NativeBuild.cs.txt', w / 'Driver.cs')
(w / 'Driver.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><Nullable>enable</Nullable></PropertyGroup></Project>')
(w / 'MODULE.bazel').write_text('''module(name="source_sdk_action")
bazel_dep(name="platforms",version="1.0.0")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path=%s)
dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")
dotnet.sdk(name="controller",version="10.0.400",platforms=["linux-arm64"])
use_repo(dotnet,"controller")
register_toolchains("//:produced_registered","//:produced_runtime_registered")
''' % json.dumps(str(rules)))
(w / 'BUILD.bazel').write_text('''load(":source_action.bzl","source_sdk","sdk_layout")
load("@rules_msbuild//msbuild:sdk.bzl","msbuild_sdk")
load("@rules_msbuild//msbuild:defs.bzl","msbuild_test")
source_sdk(name="sdk",driver_sdk="@controller//:sdk_host",driver_project="Driver.csproj",driver_source="Driver.cs",sandbox="bwrap",native_tools="native.tar",sources="sources.tar",bootstrap="bootstrap.tar",exec_compatible_with=["@platforms//os:linux","@platforms//cpu:aarch64"])
filegroup(name="evidence",srcs=[":sdk"],output_group="evidence")
filegroup(name="driver",srcs=[":sdk"],output_group="driver")
sdk_layout(name="layout",archive=":sdk")
filegroup(name="dotnet",srcs=[":layout"],output_group="dotnet")
msbuild_sdk(name="produced",dotnet=":dotnet",files=[":layout"],sdk_version="10.0.100",runtime_version="10.0.0",runtime_identifier="linux-arm64")
msbuild_test(name="smoke",project="App.csproj",srcs=["App.cs"],target_framework="net10.0",use_apphost=False)
''')
(w / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
(w / 'App.cs').write_text('System.Console.WriteLine("SDK_FROM_SOURCE="+System.Environment.Version); return System.Environment.Version.ToString()=="10.0.0" ? 0 : 1;')
report = {'sourceRevision': pin['sourceRevision'], 'sourceArchiveSha256': pin['sourceArchive']['sha256'],
          'bootstrapArtifactsSha256': digest(bootstrap_archive),
          'bootstrapSdkVersion': subprocess.check_output([baseline / '.dotnet/dotnet', '--version'], cwd='/tmp', text=True).strip(),
          'inputs': {name: {'sha256': digest(w / name), 'bytes': (w / name).stat().st_size}
                     for name in ['sources.tar', 'bootstrap.tar', 'native.tar', 'bwrap']},
          'nativePackages': subprocess.check_output(['dpkg-query', '-W'], text=True).splitlines()}
(w / 'acquisition.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({key: value for key, value in report.items() if key != 'nativePackages'}, indent=2), flush=True)
