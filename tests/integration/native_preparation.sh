#!/usr/bin/env bash
set -euo pipefail
native_helpers="$PWD/$NATIVE_HELPERS"
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
mkdir -p "$scratch/helpers" native
tar -xf "$native_helpers" -C "$scratch/helpers"
cp "$scratch/helpers/tests/runtime/NativeBuild.cs.txt" native/NativeBuild.cs
cp "$scratch/helpers/tests/runtime/NativePreparation.cs.txt" native/NativePreparation.cs
cp "$scratch/helpers/tests/runtime/native_action.bzl" native/
cp "$scratch/helpers/tests/runtime/native_inputs.bzl" native/
cp "$scratch/helpers/tests/runtime/source_repository.bzl" .
python3 - <<'PY'
from pathlib import Path
module=Path('MODULE.bazel')
text=module.read_text()
first=text.index('dotnet.sdk(');last=text.index('use_repo(dotnet',first)
text=text[:first]+'''dotnet.sdk_archive(name="dotnet",version="10.0.400",runtime_version="10.0.11",platform="linux-arm64",urls=["https://builds.dotnet.microsoft.com/dotnet/Sdk/10.0.400/dotnet-sdk-10.0.400-linux-arm64.tar.gz"],integrity="sha512-obRdpY5Vkf/5CaYSasa/we+cErxywGJfeBXoOoK+GpAjF+6Wkmy7+BMkpFxqvy7YECohbQUHh5zBZhWa940bdw==")
'''+text[last:]
module.write_text(text)
PY
cat > native/Task.csproj <<'XML'
<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><StartupObject>NativePreparation</StartupObject></PropertyGroup></Project>
XML
cat > native/BUILD.bazel <<'BUILD'
load(":native_action.bzl", "native_graph_driver")
load(":native_inputs.bzl", "native_inputs")
native_graph_driver(name="driver",sources=["NativePreparation.cs"])
native_inputs(name="sources",commit="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",packages={})
BUILD
echo 'exports_files(["source_repository.bzl"])' > BUILD.bazel
cat >> MODULE.bazel <<'MODULE'
bazel_dep(name="rules_pkg",version="1.3.0")
bazel_dep(name="rules_python",version="1.7.0")
runtime_source=use_repo_rule("//:source_repository.bzl","runtime_source")
MODULE
cp MODULE.bazel module.template
cat > write-source.py <<'PY'
import hashlib,io,json,sys,tarfile
from pathlib import Path
patch,body,broken=sys.argv[1:]
fields=['RuntimeAssemblyMajorVersion','RuntimeAssemblyMinorVersion','RuntimeFileMajorVersion','RuntimeFileMinorVersion',
 'RuntimeFileBuildVersion','RuntimeFileRevisionVersion','RuntimeProductMajorVersion','RuntimeProductMinorVersion','RuntimeProductPatchVersion','RuntimeProductVersion']
files={'eng/Versions.props':'<Project><PropertyGroup><ProductVersion>10.0.'+patch+'</ProductVersion><MajorVersion>'+('9' if broken=='yes' else '10')+'</MajorVersion><MinorVersion>0</MinorVersion><PatchVersion>'+patch+'</PatchVersion></PropertyGroup></Project>',
 'eng/native/version/_version.h':'#define VER_PRODUCTVERSION 00,00,00,00000\n#define VER_PRODUCTVERSION_STR "0.0.0"\n',
 'eng/native/version/runtime_version.h':''.join('#define '+name+' 0\n' for name in fields),
 'eng/native/version/_version.c':'const char *version="@(#)No version information produced";\n',
 'eng/common/native/common-library.sh':'# shared native build helpers\n',
 'src/native/external/libunwind/README':'upstream readme\n',
 'src/native/body.c':body,'src/native/external/brotli/BUILD.bazel':'# upstream BUILD must remain source data\n',
 'src/native/external/brotli/fixture.c':'nested source', 'src/coreclr/run.sh':'#!/bin/sh\nexit 0\n'}
archive=Path('source-archive').resolve()  # Upstream commit URLs also lack a tar suffix.
with tarfile.open(archive,'w:gz') as output:
 for name,text in sorted(files.items()):
  entry=tarfile.TarInfo('runtime-'+'a'*40+'/'+name);data=text.encode();entry.size=len(data)
  entry.mode=0o755 if name.endswith('.sh') else 0o644
  output.addfile(entry,io.BytesIO(data))
Path('MODULE.bazel').write_text(Path('module.template').read_text()+'runtime_source(name="runtime_source",urls=['+json.dumps(archive.as_uri())+'],sha256='+json.dumps(hashlib.sha256(archive.read_bytes()).hexdigest())+',commit="'+'a'*40+'")\n')
Path('native/driver-contract.json').write_text(json.dumps(dict(Version=1,Entry='Task.csproj',SdkVersion='10.0.400',Properties=dict(Configuration='Release'),SharedInputs=[],Projects={'Task.csproj':dict(Inputs=['Task.csproj','NativeBuild.cs','NativePreparation.cs'],OutputDirectories=['bin/Release/net10.0','obj/Release/net10.0'])})))
PY
python3 write-source.py 0 first no
bazel build //native:sources --disk_cache="$scratch/cache"
python3 - <<'PY'
from pathlib import Path
import tarfile
with tarfile.open('bazel-bin/native/sources.tar') as archive:
 members={m.name.removeprefix('./'):m for m in archive if m.isfile()}
 assert 'src/native/external/brotli/fixture.c' in members
 assert archive.extractfile(members['src/native/external/brotli/BUILD.bazel']).read().startswith(b'# upstream BUILD')
 assert 'eng/Versions.props' not in members
 assert members['src/coreclr/run.sh'].mode & 0o111
 assert not members['artifacts/obj/_version.h'].mode & 0o111
 assert b'10.0.0 @Commit:' in archive.extractfile(members['artifacts/obj/_version.c']).read()
Path('version.sha').write_bytes(Path('bazel-bin/native/versions/_version.c').read_bytes())
PY
python3 write-source.py 0 changed no
bazel build //native:sources --disk_cache="$scratch/cache" --execution_log_json_file="$TEST_TMPDIR/body.json"
python3 - "$TEST_TMPDIR/body.json" <<'PY'
import json,sys,tarfile
from pathlib import Path
text=Path(sys.argv[1]).read_text();decoder=json.JSONDecoder();executed=[]
while text.strip():
 row,end=decoder.raw_decode(text.lstrip());text=text.lstrip()[end:]
 if not row.get('cacheHit'):executed.append(row.get('mnemonic'))
assert 'RuntimeNativeVersions' not in executed,executed
assert Path('version.sha').read_bytes()==Path('bazel-bin/native/versions/_version.c').read_bytes()
with tarfile.open('bazel-bin/native/sources.tar') as archive:
 member=next(m for m in archive if m.name.removeprefix('./')=='src/native/body.c')
 assert archive.extractfile(member).read()==b'changed'
PY
python3 write-source.py 1 changed no
bazel build //native:sources --disk_cache="$scratch/cache"
grep -Fq 'Version 10.0.1 @Commit:' bazel-bin/native/versions/_version.c
python3 write-source.py 1 changed yes
if bazel build //native:sources --disk_cache="$scratch/cache" > "$TEST_TMPDIR/rejected.log" 2>&1; then
    echo 'Inconsistent native version was accepted' >&2; exit 1
fi
assert_contains "$TEST_TMPDIR/rejected.log" 'Native product version fields disagree'
python3 write-source.py 1 changed no
bazel build //native:sources --disk_cache="$scratch/cache"
echo 'PASS: native sources, nested BUILD data, version invalidation/reuse and failed-build recovery'

mkdir -p fixture-deb/DEBIAN fixture-deb/usr/bin fixture-deb/usr/share/doc/fixture fixture-deb/etc
cat > fixture-deb/DEBIAN/control <<'CONTROL'
Package: fixture
Version: 1.0
Architecture: all
Maintainer: fixture
Description: declared native tool archive control
CONTROL
printf '#!/bin/sh\nprintf "DECLARED_TOOL\\n"\n' > fixture-deb/usr/bin/tool
chmod +x fixture-deb/usr/bin/tool
ln -s tool fixture-deb/usr/bin/alias
printf 'fixture license\n' > fixture-deb/usr/share/doc/fixture/copyright
printf 'fixture config\n' > fixture-deb/etc/config
dpkg-deb --build fixture-deb fixture.deb >/dev/null
python3 - <<'PY'
import hashlib
from pathlib import Path
with Path('BUILD.bazel').open('a') as build:
 build.write('\nload("@rules_msbuild//msbuild:defs.bzl","msbuild_native_toolchain_packages")\n')
 build.write('msbuild_native_toolchain_packages(name="tool_fixture",packages={"fixture.deb":"'+hashlib.sha256(Path('fixture.deb').read_bytes()).hexdigest()+'"},archive=True)\n')
 build.write('filegroup(name="tool_archive",srcs=[":tool_fixture"],output_group="archive")\n')
PY
bazel build //:tool_archive --disk_cache="$scratch/cache"
python3 - <<'PY'
import tarfile
with tarfile.open('bazel-bin/tool_fixture.tar') as archive:
 members={member.name.removeprefix('./'):member for member in archive}
 assert members['usr/bin/alias'].issym() and members['usr/bin/alias'].linkname=='tool'
 assert members['usr/bin/tool'].mode & 0o111
 assert all(member.mtime==0 for member in members.values())
 assert archive.extractfile(members['usr/bin/tool']).read().startswith(b'#!/bin/sh')
print('PASS: complete native package tree and link-preserving archive output group')
PY
