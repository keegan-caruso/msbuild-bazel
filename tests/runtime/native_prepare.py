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
import tempfile

from native_driver import write_contract

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path, help='pinned Git checkout or verified runtime source tar.gz')
parser.add_argument('--jobs', type=int, default=4)
parser.add_argument('--ninja', action='store_true')
parser.add_argument('workspace', type=Path)
args = parser.parse_args()
assert platform.system() == 'Linux' and platform.machine() == 'aarch64', 'Qualified environment is Linux ARM64'
source, workspace = args.source.resolve(), args.workspace.resolve()
assert args.jobs > 0
folder = workspace/'native'
folder.mkdir(exist_ok=False)
here = Path(__file__).resolve().parent
commit = '60629d14374c56f1cb51819049ad1fa529307f8d'
temporary = None
if source.is_file():
    source_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    assert source_sha256 == '4fae24371e108a046d7bfd30785e9a2f4400552b165b70300a72f855370da3de', 'Pinned runtime source archive changed'
    temporary = tempfile.TemporaryDirectory(prefix='runtime-native-source-')
    prefixes = ['src/coreclr/', 'src/native/', 'eng/native/', 'eng/common/native/']
    prefix = 'runtime-' + commit + '/'
    with tarfile.open(source) as archive:
        members = [member for member in archive if member.name.startswith(prefix) and
                   any(member.name[len(prefix):].startswith(part) for part in prefixes)]
        archive.extractall(temporary.name, members=members, filter='data')
    source = Path(temporary.name) / ('runtime-' + commit)
    paths = sorted(str(path.relative_to(source)) for path in source.rglob('*') if path.is_file() or path.is_symlink())
else:
    assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()==commit
    source_sha256 = None
    paths = subprocess.check_output(['git','ls-files','src/coreclr','src/native','eng/native','eng/common/native'],cwd=source,text=True).splitlines()


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
with tarfile.open(folder/'source.tar','w') as archive:
    for name in paths:
        path=source/name
        if path.is_file() or path.is_symlink(): archive.add(path,arcname=name,recursive=False,filter=normalize)
    import io
    version=(source/'eng/native/version/_version.c').read_text()
    version=version.replace('@(#)No version information produced','@(#)Version 10.0.0 @Commit: '+commit)
    headers={name:(source/'eng/native/version'/name).read_text() for name in ['_version.h','runtime_version.h']}
    headers['_version.h']=headers['_version.h'].replace('00,00,00,00000','10,0,0,0').replace('"0.0.0"','"10.0.0"')
    headers['runtime_version.h']=headers['runtime_version.h'].replace('MajorVersion 0','MajorVersion 10').replace('RuntimeProductVersion 0.0.0-dev','RuntimeProductVersion 10.0.0')
    additions={**{'artifacts/obj/'+name:text for name,text in headers.items()}, 'artifacts/obj/_version.c':version, 'build-native.sh':f'''set -euo pipefail
./src/coreclr/build-runtime.sh -arm64 -release -component runtime -component jit -component hosts -numproc {args.jobs}{" -ninja" if args.ninja else ""}
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
write_contract(folder)
(folder/'BUILD.bazel').write_text('''load(":native_action.bzl","native_graph_driver","native_runtime")
native_graph_driver(name="driver")
native_runtime(name="runtime",driver=":driver",sandbox="bwrap",toolchain_archive="toolchain.tar",source_archive="source.tar",visibility=["//visibility:public"])
filegroup(name="coreclr",srcs=[":runtime"],output_group="coreclr",visibility=["//visibility:public"])
filegroup(name="jit",srcs=[":runtime"],output_group="jit",visibility=["//visibility:public"])
filegroup(name="host",srcs=[":runtime"],output_group="host",visibility=["//visibility:public"])
''')
report={'commit':commit,'sourceArchiveSha256':source_sha256,'jobs':args.jobs,'generator':'Ninja' if args.ninja else 'Unix Makefiles','sourceFiles':len(paths),'inputs':{name:{'sha256':digest(folder/name),'bytes':(folder/name).stat().st_size} for name in ['toolchain.tar','source.tar','bwrap']},'packages':subprocess.check_output(['dpkg-query','-W','-f=${Package}\t${Version}\n'],text=True).splitlines()}
(folder/'acquisition.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='packages'}),flush=True)

if temporary is not None: temporary.cleanup()
