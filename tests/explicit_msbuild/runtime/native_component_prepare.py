"""Declare a bounded native support or host product using the pinned native inputs."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('native',type=Path)
p.add_argument('output',type=Path)
p.add_argument('component',choices=['support','host','crypto','compression'])
a=p.parse_args();folder=a.output.resolve();folder.mkdir(parents=True,exist_ok=False)
here=Path(__file__).resolve().parent
commit='60629d14374c56f1cb51819049ad1fa529307f8d'
shared='shared/Microsoft.NETCore.App/10.0.11/'
if a.component!='host':
    target,subdir,group={
        'support':('System.Native','System.Native','system_native'),
        'crypto':('System.Security.Cryptography.Native.OpenSsl','System.Security.Cryptography.Native','openssl'),
        'compression':('System.IO.Compression.Native','System.IO.Compression.Native','compression'),
    }[a.component]
    filename='lib'+target+'.so'
    products={group:filename}
    destinations={filename:shared+filename}
    script=f'''./src/native/libs/build-native.sh -arm64 -release -outconfig qualification -configureonly -numproc 6
cmake --build artifacts/obj/native/qualification --target {target} --parallel 6
mkdir result
cp artifacts/obj/native/qualification/{subdir}/{filename} result/
'''
else:
    products={'muxer':'dotnet','fxr':'libhostfxr.so','policy':'libhostpolicy.so'}
    destinations={'dotnet':'dotnet','libhostfxr.so':'host/fxr/10.0.0/libhostfxr.so','libhostpolicy.so':shared+'libhostpolicy.so'}
    script=f'''./src/native/corehost/build.sh -arm64 -release -commithash {commit} -numproc 6
mkdir result
cp artifacts/bin/linux-arm64.Release/corehost/dotnet result/
cp artifacts/bin/linux-arm64.Release/corehost/libhostfxr.so result/
cp artifacts/bin/linux-arm64.Release/corehost/libhostpolicy.so result/
'''
script='set -euo pipefail\n'+script+'tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -cf result.tar -C result .\n'
# The pinned native archive already owns the complete tracked native tree.
# The header bootstrap is explicit because no managed Arcade build runs here.
with tarfile.open(a.native/'source.tar') as original,tarfile.open(folder/'source.tar','w') as out:
    for member in original:
        if member.name=='build-native.sh':continue
        out.addfile(member,original.extractfile(member) if member.isfile() else None)
    headers={name:original.extractfile('eng/native/version/'+name).read().decode() for name in ['_version.h','runtime_version.h']}
    headers['_version.h']=headers['_version.h'].replace('00,00,00,00000','10,0,0,0').replace('"0.0.0"','"10.0.0"')
    headers['runtime_version.h']=headers['runtime_version.h'].replace('MajorVersion 0','MajorVersion 10').replace('RuntimeProductVersion 0.0.0-dev','RuntimeProductVersion 10.0.0')
    for name,text in {'build-native.sh':script,**{'artifacts/obj/'+n:v for n,v in headers.items()}}.items():
        data=text.encode();member=tarfile.TarInfo(name);member.size=len(data);member.mode=0o644;out.addfile(member,io.BytesIO(data))
for name in ['toolchain.tar','bwrap']:os.link(a.native/name,folder/name)
shutil.copyfile(here/'NativeBuild.cs.txt',folder/'NativeBuild.cs')
shutil.copyfile(here/'native_action.bzl',folder/'native_action.bzl')
shutil.copyfile(a.native/'Task.csproj',folder/'Task.csproj')
(folder/'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl","msbuild_binary")
load(":native_action.bzl","native_runtime")
msbuild_binary(name="driver",project="Task.csproj",srcs=["NativeBuild.cs"],target_framework="net10.0",linux_worker=True)
native_runtime(name="runtime",driver=":driver",sandbox="bwrap",toolchain_archive="toolchain.tar",source_archive="source.tar",products='''+json.dumps(products)+''',visibility=["//visibility:public"])
'''+''.join('filegroup(name='+json.dumps(group)+',srcs=[":runtime"],output_group='+json.dumps(group)+',visibility=["//visibility:public"])\n' for group in products))
(folder/'products.json').write_text(json.dumps(dict(products=products,destinations=destinations),indent=2)+'\n')
(folder/'acquisition.json').write_text(json.dumps(dict(commit=commit,component=a.component,version='10.0.0',sourceSha256=hashlib.sha256((folder/'source.tar').read_bytes()).hexdigest()),indent=2)+'\n')
