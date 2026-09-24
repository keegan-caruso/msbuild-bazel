"""Add actual Avalonia Native IDL generation to the theme graph's cache control."""
import base64,hashlib,json,shutil,sys,urllib.request
from pathlib import Path
workspace=Path(sys.argv[1]);upstream=Path(sys.argv[2]);root=workspace/'upstream';control=root/'cache-controls';control.mkdir()
shutil.copyfile(upstream/'src/Avalonia.Native/avn.idl',control/'input.idl')
archive=urllib.request.urlopen('https://api.nuget.org/v3-flatcontainer/microcom.codegenerator.msbuild/0.11.0/microcom.codegenerator.msbuild.0.11.0.nupkg').read();sha=hashlib.sha256(archive).hexdigest();assert sha=='4ecc73897f55f13dea46b100de8f7063ce28703714514073bc0462e50656db7a';(control/'microcom.nupkg').write_bytes(archive)
(control/'Generate.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="MicroCom.CodeGenerator.MSBuild" Version="0.11.0" PrivateAssets="all"/><MicroComIdl Include="input.idl" CSharpInteropPath="$(GeneratedSource)"/></ItemGroup></Project>')
(control/'adapter.targets').write_text('<Project><Target Name="BindGeneratedFile" BeforeTargets="GenerateMicroComItems"><ItemGroup><MicroComIdl Update="@(MicroComIdl)"><CSharpInteropPath>$(GeneratedSource)</CSharpInteropPath></MicroComIdl></ItemGroup></Target></Project>')
build=root/'BUILD.bazel';text=build.read_text();text='load("@rules_msbuild//msbuild:defs.bzl","msbuild_generate")\n'+text
text+=f'msbuild_nuget_package(name="cache_microcom",package_id="MicroCom.CodeGenerator.MSBuild",version="0.11.0",archive="cache-controls/microcom.nupkg",archive_sha256="{sha}",content_hash="{base64.b64encode(hashlib.sha512(archive).digest()).decode()}")\n'
text+='''msbuild_items(name="cache_idl_input",item_type="MicroComIdl",srcs=["cache-controls/input.idl"])
msbuild_generate(name="cache_idl",project="cache-controls/Generate.csproj",target_framework="net10.0",build_deps=[":cache_microcom"],package_private_assets={"MicroCom.CodeGenerator.MSBuild":"all"},items=[":cache_idl_input"],adapter_imports=["cache-controls/adapter.targets"],targets=["GenerateMicroComItems"],outputs=["Interop.Generated.cs"],output_properties={"GeneratedSource":"Interop.Generated.cs"},linux_worker=True)
filegroup(name="cache_benchmark",srcs=[":benchmark",":cache_idl"])
''';build.write_text(text)
paths={'tool':'src/Avalonia.Build.Tasks/GenerateAvaloniaResourcesTask.cs','xaml':'src/Avalonia.Themes.Simple/SimpleTheme.xaml','idl':'cache-controls/input.idl'}
(workspace/'remote-originals.json').write_text(json.dumps({kind:dict(path=path,text=(root/path).read_text()) for kind,path in paths.items()}))
