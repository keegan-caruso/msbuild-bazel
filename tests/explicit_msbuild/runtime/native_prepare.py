"""Acquire explicit Linux native tool/source archives and emit a generation action.

Setup may inspect the qualified container; the build action has no network or
access to its source checkout or tool installation. Runtime choices stay here.
"""
import argparse
import hashlib
import json
import os
import posixpath
import platform
from pathlib import Path
import shutil
import subprocess
import tarfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path)
parser.add_argument('workspace', type=Path)
args = parser.parse_args()
assert platform.system() == 'Linux' and platform.machine() == 'aarch64', 'Qualified environment is Linux ARM64'
source, workspace = args.source.resolve(), args.workspace.resolve()
folder = workspace/'native'
folder.mkdir(exist_ok=False)
here = Path(__file__).resolve().parent
commit = '60629d14374c56f1cb51819049ad1fa529307f8d'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()==commit

def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): h.update(block)
    return h.hexdigest()

def normalize(entry):
    entry.uid=entry.gid=entry.mtime=0
    entry.uname=entry.gname=''
    if entry.issym() and entry.linkname.startswith('/'):
        entry.linkname=posixpath.relpath(entry.linkname, '/'+posixpath.dirname(entry.name))
    return entry

# Include the compiler's distribution filesystem (including dynamic loader,
# libc, headers, Python and CMake modules), not the installed .NET SDK or caches.
with tarfile.open(folder/'toolchain.tar','w') as archive:
    for name in ['usr','bin','lib','sbin','etc/alternatives','etc/ld.so.conf','etc/ld.so.conf.d','etc/ld.so.cache','etc/os-release']:
        archive.add('/'+name, arcname=name, filter=normalize)
    for name in ['source','proc','dev','tmp']:
        entry=tarfile.TarInfo(name);entry.type=tarfile.DIRTYPE;entry.mode=0o755;archive.addfile(entry)
shutil.copy2('/usr/bin/bwrap',folder/'bwrap')
# Only tracked native build inputs: no raw artifacts, git database or NuGet cache.
paths=subprocess.check_output(['git','ls-files','src/coreclr','src/native','eng/native','eng/common/native'],cwd=source,text=True).splitlines()
with tarfile.open(folder/'source.tar','w') as archive:
    for name in paths:
        path=source/name
        if path.is_file() or path.is_symlink(): archive.add(path,arcname=name,recursive=False,filter=normalize)
    import io
    version=(source/'eng/native/version/_version.c').read_text()
    version=version.replace('@(#)No version information produced','@(#)Version 10.0.0 @Commit: '+commit)
    additions={'artifacts/obj/_version.c':version, 'build-native.sh':'''set -euo pipefail
./src/coreclr/build-runtime.sh -arm64 -release -component runtime -component jit -component hosts -numproc 6
mkdir result
cp artifacts/bin/coreclr/linux.arm64.Release/libcoreclr.so result/
cp artifacts/bin/coreclr/linux.arm64.Release/libclrjit.so result/
cp artifacts/bin/coreclr/linux.arm64.Release/corerun result/
tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -cf result.tar -C result .
'''}
    for name,text in additions.items():
        entry=tarfile.TarInfo(name);data=text.encode();entry.size=len(data);entry.mode=0o644;archive.addfile(entry,io.BytesIO(data))
shutil.copyfile(here/'NativeBuild.cs.txt',folder/'NativeBuild.cs')
(folder/'Task.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup></Project>')
shutil.copyfile(here/'native_action.bzl',folder/'native_action.bzl')
(folder/'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl","msbuild_binary")
load(":native_action.bzl","native_runtime")
msbuild_binary(name="driver",project="Task.csproj",srcs=["NativeBuild.cs"],target_framework="net10.0",linux_worker=True)
native_runtime(name="runtime",driver=":driver",sandbox="bwrap",toolchain_archive="toolchain.tar",source_archive="source.tar",visibility=["//visibility:public"])
filegroup(name="coreclr",srcs=[":runtime"],output_group="coreclr",visibility=["//visibility:public"])
filegroup(name="jit",srcs=[":runtime"],output_group="jit",visibility=["//visibility:public"])
filegroup(name="host",srcs=[":runtime"],output_group="host",visibility=["//visibility:public"])
''')
report={'commit':commit,'sourceFiles':len(paths),'inputs':{name:{'sha256':digest(folder/name),'bytes':(folder/name).stat().st_size} for name in ['toolchain.tar','source.tar','bwrap']},'packages':subprocess.check_output(['dpkg-query','-W','-f=${Package}\t${Version}\n'],text=True).splitlines()}
(folder/'acquisition.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='packages'}),flush=True)
