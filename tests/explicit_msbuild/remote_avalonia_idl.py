"""Pinned Avalonia IDL generation: raw MSBuild parity and remote execution."""
import argparse
import base64
import hashlib
import os
from pathlib import Path
import subprocess
import urllib.request
from remote_support import RemoteFixture

COMMIT='37fbd9655cc581ff5b1c6b1fb1be4e3118c889d0'
INPUTS={
 'src/Avalonia.Native/avn.idl':'99e0c1b4ebd881d9f1601c5800c807b7333ffc1ab6754de88d26aec88d45c365',
 'src/Windows/Avalonia.Win32/Win32Com/win32.idl':'c5e8812f3328f2b1419b7d3ca2a51f50a818bfcff03f39149d29878aae54c2e0',
 'src/Windows/Avalonia.Win32/WinRT/winrt.idl':'beab780d1eeae010e9605365f1b397e03c1253cf457f1d3bfba0e2c39a569b76',
 'src/Windows/Avalonia.Win32/DirectX/directx.idl':'a3d884d87e0b435e2203d233de8f32312670ffda8a9f37d33f570f7fa6497183',
 'src/Windows/Avalonia.Win32/DComposition/dcomp.idl':'ecf8aee1bdaca317aee18f84fa1fb64cf2eaa0e28027fbf3ceaa9eb5a0449ae1',
}
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('output',type=Path);p.add_argument('--executor',required=True)
p.add_argument('--recover-workspace',type=Path)
a=p.parse_args();f=RemoteFixture(a.output,a.executor,a.recover_workspace);f.sdk()
if a.recover_workspace:
    try:
        rows=f.run('independent-recovery',['//:generate'],[],command='build')
        assert rows and all(x.get('cacheHit') for x in rows),rows
        assert any(x['mnemonic']=='MSBuildGenerate' for x in rows)
        assert hashlib.sha256((f.workspace/'bazel-bin/generate.generated/Interop.Generated.cs').read_bytes()).hexdigest()==(f.workspace/'expected.sha256').read_text()
    finally:f.shutdown()
    raise SystemExit()
raw=f.folder/'raw';raw.mkdir()
project='<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="MicroCom.CodeGenerator.MSBuild" Version="0.11.0" PrivateAssets="all" /></ItemGroup><ItemGroup><MicroComIdl Include="input.idl" CSharpInteropPath="$(GeneratedSource)" /></ItemGroup></Project>'
f.put('Generate.csproj',project);(raw/'Generate.csproj').write_text(project)
archive=urllib.request.urlopen('https://api.nuget.org/v3-flatcontainer/microcom.codegenerator.msbuild/0.11.0/microcom.codegenerator.msbuild.0.11.0.nupkg').read()
digest=hashlib.sha256(archive).hexdigest();assert digest=='4ecc73897f55f13dea46b100de8f7063ce28703714514073bc0462e50656db7a'
(f.workspace/'microcom.nupkg').write_bytes(archive)
feed=f.folder/'feed';feed.mkdir();(feed/'MicroCom.CodeGenerator.MSBuild.0.11.0.nupkg').write_bytes(archive)
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'
subprocess.run([sdk,'restore',raw/'Generate.csproj','--source',feed,'-p:RestorePackagesPath='+str(f.folder/'packages'),'-p:NuGetAudit=false'],check=True,stdout=subprocess.DEVNULL)
f.put('BUILD.bazel','''load("@rules_msbuild//msbuild:defs.bzl","msbuild_generate","msbuild_items","msbuild_nuget_package")
'''+f'msbuild_nuget_package(name="microcom",package_id="MicroCom.CodeGenerator.MSBuild",version="0.11.0",archive="microcom.nupkg",archive_sha256="{digest}",content_hash="{base64.b64encode(hashlib.sha512(archive).digest()).decode()}")\n'+'''msbuild_items(name="idl",item_type="MicroComIdl",srcs=["input.idl"])
msbuild_generate(name="generate",project="Generate.csproj",target_framework="net10.0",build_deps=[":microcom"],package_private_assets={"MicroCom.CodeGenerator.MSBuild":"all"},items=[":idl"],adapter_imports=["adapter.targets"],targets=["GenerateMicroComItems"],outputs=["Interop.Generated.cs"],output_properties={"GeneratedSource":"Interop.Generated.cs"},linux_worker=True,allow_remote_execution=True)
''')
f.put('adapter.targets','<Project><Target Name="BindGeneratedFile" BeforeTargets="GenerateMicroComItems"><ItemGroup><MicroComIdl Update="@(MicroComIdl)"><CSharpInteropPath>$(GeneratedSource)</CSharpInteropPath></MicroComIdl></ItemGroup></Target></Project>')
parity=[]
try:
    for i,(name,expected) in enumerate(INPUTS.items()):
        data=urllib.request.urlopen('https://raw.githubusercontent.com/AvaloniaUI/Avalonia/'+COMMIT+'/'+name).read()
        assert hashlib.sha256(data).hexdigest()==expected,name
        (f.workspace/'input.idl').write_bytes(data);(raw/'input.idl').write_bytes(data)
        output=raw/'Interop.Generated.cs'
        if output.exists():output.unlink()
        result=subprocess.run([sdk,'msbuild',raw/'Generate.csproj','-t:GenerateMicroComItems','-p:RestorePackagesPath='+str(f.folder/'packages'),'-p:GeneratedSource='+str(output)],text=True,capture_output=True)
        (f.folder/('raw-'+str(i)+'.log')).write_text(result.stdout+result.stderr);assert result.returncode==0,result.stdout+result.stderr
        f.run('idl-'+str(i),['//:generate'],[('MSBuildGenerate','//:generate')],command='build',cold=i==0)
        generated=(f.workspace/'bazel-bin/generate.generated/Interop.Generated.cs').read_bytes()
        assert generated==output.read_bytes(),name
        parity.append(dict(input=name,sha256=hashlib.sha256(generated).hexdigest(),bytes=len(generated)))
    import json
    (f.folder/'parity.json').write_text(json.dumps(dict(commit=COMMIT,files=parity),indent=2)+'\n')
    f.put('expected.sha256',parity[-1]['sha256'])
finally:f.shutdown()
