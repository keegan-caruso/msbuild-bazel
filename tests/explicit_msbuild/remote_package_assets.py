"""Binary NuGet references and RID-selected managed/native assets on an SDK-free executor."""
import argparse
import base64
import hashlib
import os
from pathlib import Path
import subprocess
import zipfile
from remote_support import RemoteFixture

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('output',type=Path);p.add_argument('--executor',required=True)
p.add_argument('--recover-workspace',type=Path)
a=p.parse_args();f=RemoteFixture(a.output,a.executor,a.recover_workspace);f.sdk()
if a.recover_workspace:
    try:
        rows=f.run('independent-recovery',['//:test'],[],tests=[])
        assert rows and all(x.get('cacheHit') for x in rows),rows
        assert any(x['mnemonic']=='MSBuildNugetExtract' for x in rows)
    finally:f.shutdown()
    raise SystemExit()
# Fixture acquisition runs on the client; only the resulting explicit archive is an action input.
producer=f.folder/'package-source';producer.mkdir()
(producer/'Fixture.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
(producer/'Api.cs').write_text('public static class PackageApi { public static int Value() => 7; }')
dotnet=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'
subprocess.run([dotnet,'build',producer/'Fixture.csproj','-c','Release','-p:NuGetAudit=false'],check=True,stdout=subprocess.DEVNULL)
managed=(producer/'bin/Release/net10.0/Fixture.dll').read_bytes()
reference=(producer/'obj/Release/net10.0/ref/Fixture.dll').read_bytes()
(producer/'Api.cs').write_text('public static class PackageApi { public static int Value() => 99; }')
subprocess.run([dotnet,'build',producer/'Fixture.csproj','-c','Release','-p:NuGetAudit=false'],check=True,stdout=subprocess.DEVNULL)
fallback=(producer/'bin/Release/net10.0/Fixture.dll').read_bytes()
assert fallback != managed

def pack(native_value, include_native=True):
    (producer/'native.c').write_text('int fixture_value(void) { return '+str(native_value)+'; }')
    subprocess.run(['gcc','-shared','-fPIC','-nostdlib','-o',str(producer/'libfixture.so'),str(producer/'native.c')],check=True)
    entries={'Fixture.Assets.nuspec':b'<package><metadata><id>Fixture.Assets</id><version>1.0.0</version><authors>fixture</authors><description>RID control</description></metadata></package>', 'ref/net10.0/Fixture.dll':reference,'lib/net10.0/Fixture.dll':fallback,'runtimes/linux-arm64/lib/net10.0/Fixture.dll':managed,'runtimes/linux-x64/lib/net10.0/Fixture.dll':b'wrong RID managed sentinel','runtimes/linux-x64/native/libfixture.so':b'wrong RID native sentinel'}
    if include_native:entries['runtimes/linux-arm64/native/libfixture.so']=(producer/'libfixture.so').read_bytes()
    archive=f.workspace/'assets.nupkg'
    with zipfile.ZipFile(archive,'w') as z:
        for name,data in entries.items():z.writestr(zipfile.ZipInfo(name,(2020,1,1,0,0,0)),data)
    data=archive.read_bytes()
    f.put('BUILD.bazel','''load("@rules_msbuild//msbuild:defs.bzl","msbuild_test","msbuild_nuget_package")
msbuild_nuget_package(name="package",package_id="Fixture.Assets",version="1.0.0",archive="assets.nupkg",archive_sha256="'''+hashlib.sha256(data).hexdigest()+'''",content_hash="'''+base64.b64encode(hashlib.sha512(data).digest()).decode()+'''")
msbuild_test(name="test",project="Test.csproj",srcs=["Test.cs"],deps=[":package"],data=["expected.txt"],target_framework="net10.0",use_apphost=False,linux_worker=True,allow_remote_execution=True)
''')
f.put('Test.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="Fixture.Assets" Version="1.0.0" /></ItemGroup></Project>')
f.put('Test.cs','''using System.Runtime.InteropServices;
return (PackageApi.Value()+Native.Value()).ToString()==System.IO.File.ReadAllText("expected.txt") ? 0 : 1;
static class Native { [DllImport("fixture",EntryPoint="fixture_value")] internal static extern int Value(); }
''')
f.put('expected.txt','16');pack(9)
compiled=[('MSBuildAssembly','//:test')]
try:
    f.run('cold',['//:test'],compiled,cold=True,tests=['//:test'])
    f.run('noop',['//:test'],[],tests=[])
    pack(11);f.put('expected.txt','18')
    f.run('native-change',['//:test'],compiled,tests=['//:test'])
    pack(11,include_native=False)
    f.run('missing-native',['//:test'],compiled,error='DllNotFoundException',tests=['//:test'])
    pack(11)
    f.run('restored',['//:test'],[],tests=[])
finally:f.shutdown()
