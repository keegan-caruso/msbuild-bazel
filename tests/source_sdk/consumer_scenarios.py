"""Qualify packages, Razor rendering, and framework-dependent publish with a produced SDK.

Run against source_action_prepare.py's produced SDK workspace/toolchain.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import shutil
import platform
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory', type=Path)
parser.add_argument('--sdk-bundle', type=Path, help='Previously qualified source-produced SDK component bundle; verified against pin.json')
a = parser.parse_args()
folder = a.directory.resolve()
w = folder / 'source'
if a.sdk_bundle:
    assert platform.system() == 'Linux' and platform.machine() == 'aarch64'
    from source_action_recovery import digest
    pin = json.loads(Path(__file__).with_name('pin.json').read_text())
    bundle = pin['qualifiedSdkBundle']
    assert digest(a.sdk_bundle) == bundle['sha256'], 'Unqualified source SDK bundle'
    w.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(a.sdk_bundle, w / 'component.tar')
    shutil.copyfile(Path(__file__).with_name('source_action.bzl'), w / 'source_action.bzl')
    rules = Path(__file__).resolve().parents[2]
    (w / 'MODULE.bazel').write_text('module(name="source_sdk_consumers")\n'
        'bazel_dep(name="rules_msbuild",version="0.0.0")\n'
        'local_path_override(module_name="rules_msbuild",path='+json.dumps(str(rules))+')\n'
        'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
        'dotnet.sdk(name="controller",version="10.0.400",platforms=["linux-arm64"])\n'
        'use_repo(dotnet,"controller")\n'
        'register_toolchains("//:produced_registered","//:produced_runtime_registered")\n')
    (w / 'BUILD.bazel').write_text('load(":source_action.bzl","sdk_layout")\n'
        'load("@rules_msbuild//msbuild:sdk.bzl","msbuild_sdk")\n'
        'genrule(name="sdk",srcs=["component.tar"],outs=["sdk.tar.gz"],cmd='+json.dumps(
            'echo "'+bundle['sha256']+'  $(location component.tar)" | sha256sum -c - && tar -xOf $(location component.tar) '+bundle['archivePath']+' > $@')+')\n'
        'genrule(name="static_assets",srcs=["component.tar"],outs=["StaticWebAssets.nupkg"],cmd='+json.dumps('tar -xOf $(location component.tar) artifacts/packages/Release/NonShipping/sdk/Microsoft.NET.Sdk.StaticWebAssets.10.0.100-rtm.25523.111.nupkg > $@')+')\n'
        'sdk_layout(name="layout",archive=":sdk",packages={":static_assets":"sdk/10.0.100/Sdks/Microsoft.NET.Sdk.StaticWebAssets"})\n'
        'filegroup(name="dotnet",srcs=[":layout"],output_group="dotnet")\n'
        'msbuild_sdk(name="produced",dotnet=":dotnet",files=[":layout"],sdk_version="10.0.100",runtime_version="10.0.0",runtime_identifier="linux-arm64")\n')
assert (w / 'BUILD.bazel').is_file(), 'Prepare the produced SDK workspace first'


def put(name, text):
    path = w / 'scenarios' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


put('Package.csproj', '''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><PackageId>SourceSdk.Package</PackageId><Version>1.0.0</Version><GeneratePackageOnBuild>false</GeneratePackageOnBuild><PackageOutputPath>bin/Package/packages/</PackageOutputPath></PropertyGroup></Project>''')
put('Value.cs', 'public static class PackageValue { public static int Get() => 42; }')
put('PackageApp.csproj', '''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="SourceSdk.Package" Version="1.0.0" /></ItemGroup></Project>''')
put('PackageApp.cs', 'System.Console.WriteLine("SOURCE_SDK_PACKAGE="+PackageValue.Get()); return PackageValue.Get()==42 ? 0 : 1;')
put('Views.csproj', '''<Project Sdk="Microsoft.NET.Sdk.Razor"><PropertyGroup><TargetFramework>net10.0</TargetFramework><AddRazorSupportForMvc>true</AddRazorSupportForMvc></PropertyGroup><ItemGroup><FrameworkReference Include="Microsoft.AspNetCore.App" /></ItemGroup></Project>''')
put('Marker.cs', 'public class ViewMarker {}')
put('Views/Hello.cshtml', '<p>source SDK razor</p>')
put('RazorApp.csproj', '''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><FrameworkReference Include="Microsoft.AspNetCore.App" /><ProjectReference Include="Views.csproj" /></ItemGroup></Project>''')
put('RazorApp.cs', '''using System;
using System.IO;
using System.Linq;
using System.Reflection;
using Microsoft.AspNetCore.Razor.Hosting;
using Microsoft.AspNetCore.Mvc.Razor;
using Microsoft.AspNetCore.Mvc.Rendering;
var view = typeof(ViewMarker).Assembly.GetCustomAttributes<RazorCompiledItemAttribute>().Single();
var page = (RazorPage)Activator.CreateInstance(view.Type)!;
using var writer = new StringWriter();
page.ViewContext = new ViewContext { Writer = writer };
await page.ExecuteAsync();
Console.WriteLine(writer.ToString());
return writer.ToString()=="<p>source SDK razor</p>" ? 0 : 1;
''')
put('Publish.csproj', '''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><UseAppHost>false</UseAppHost><PublishDir>bin/Publish/publish/</PublishDir></PropertyGroup></Project>''')
put('Publish.cs', 'System.Console.WriteLine("SOURCE_SDK_PUBLISH");')
put('Directory.Build.props', '<Project><PropertyGroup><EnableDefaultNoneItems>false</EnableDefaultNoneItems><EnableDefaultContentItems>false</EnableDefaultContentItems><BaseOutputPath>bin/$(MSBuildProjectName)/</BaseOutputPath><BaseIntermediateOutputPath>obj/$(MSBuildProjectName)/</BaseIntermediateOutputPath><MSBuildProjectExtensionsPath>$(BaseIntermediateOutputPath)</MSBuildProjectExtensionsPath></PropertyGroup></Project>')
projects = {'Package.csproj':['Value.cs'], 'PackageApp.csproj':['PackageApp.cs'], 'Views.csproj':['Marker.cs','Views/Hello.cshtml'], 'RazorApp.csproj':['RazorApp.cs'], 'Publish.csproj':['Publish.cs']}
for project, inputs in projects.items():
    stem = project[:-7]
    path = w / 'scenarios' / project
    text = path.read_text().replace('<PropertyGroup>', '<PropertyGroup><EnableDefaultCompileItems>false</EnableDefaultCompileItems>')
    if stem in ['PackageApp','RazorApp']:
        text = text.replace('<TargetFramework>', '<OutputType>Exe</OutputType><UseAppHost>false</UseAppHost><TargetFramework>')
    text = text.replace('</Project>', '<ItemGroup>'+''.join('<Compile Include="'+name+'" />' for name in inputs if name.endswith('.cs'))+''.join('<Content Include="'+name+'" />' for name in inputs if name.endswith('.cshtml'))+'</ItemGroup></Project>')
    path.write_text(text)

def contract(name, entry, members, extra=None):
    rows = {p:dict(Inputs=[p]+projects[p],OutputDirectories=[f'bin/{p[:-7]}/Release/net10.0',f'obj/{p[:-7]}/Release/net10.0']+((extra or {}).get(p,[]))) for p in members}
    put(name+'.json',json.dumps(dict(Version=1,Entry=entry,SdkVersion='10.0.100',Properties={'Configuration':'Release'},SharedInputs=['Directory.Build.props'],Projects=rows)))
    return ['Directory.Build.props']+[file for p in members for file in [p]+projects[p]]
pack_inputs = contract('pack','Package.csproj',['Package.csproj'],{'Package.csproj':['bin/Package/packages']})
app_inputs = contract('package-app','PackageApp.csproj',['PackageApp.csproj'])
razor_inputs = contract('razor','RazorApp.csproj',['Views.csproj','RazorApp.csproj'])
publish_inputs = contract('publish','Publish.csproj',['Publish.csproj'],{'Publish.csproj':['bin/Publish/publish']})
put('BUILD.bazel', '\n'.join([
 'load("@rules_msbuild//msbuild:defs.bzl","msbuild_graph","msbuild_graph_runner","msbuild_graph_output","msbuild_graph_test","msbuild_generated_nuget_package","msbuild_package_lock","msbuild_graph_layout")',
 'msbuild_graph_runner(name="runner")',
 'msbuild_graph(name="pack_graph",target="Pack",runner=":runner",contract="pack.json",source_root="scenarios",srcs='+json.dumps(pack_inputs)+')',
 'msbuild_graph_output(name="pack",graph=":pack_graph",path="bin/Package/packages/SourceSdk.Package.1.0.0.nupkg")',
 'msbuild_generated_nuget_package(name="package",package_id="SourceSdk.Package",version="1.0.0",archive=":pack")',
 'msbuild_package_lock(name="lock",packages=[":package"])',
 'msbuild_graph(name="package_graph",runner=":runner",contract="package-app.json",source_root="scenarios",srcs='+json.dumps(app_inputs)+',package_lock=":lock",project_outputs={"PackageApp.csproj|net10.0":["bin/PackageApp/Release/net10.0","PackageApp.dll","Exe"]})',
 'msbuild_graph_test(name="package_test",graph=":package_graph",project="PackageApp.csproj")',
 'msbuild_graph(name="razor_graph",runner=":runner",contract="razor.json",source_root="scenarios",srcs='+json.dumps(razor_inputs)+',project_outputs={"RazorApp.csproj|net10.0":["bin/RazorApp/Release/net10.0","RazorApp.dll","Exe"]})',
 'msbuild_graph_test(name="razor_test",graph=":razor_graph",project="RazorApp.csproj")',
 'msbuild_graph(name="publish_graph",target="Publish",runner=":runner",contract="publish.json",source_root="scenarios",srcs='+json.dumps(publish_inputs)+',publish_outputs={"Publish.csproj|net10.0":["bin/Publish/publish","Publish.dll","Exe"]})',
 'msbuild_graph_layout(name="publish",graph=":publish_graph",project="Publish.csproj")','']))
base = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base=' + str(folder / 'base'), '--ignore_all_rc_files']
reports = []
try:
    for case, command, targets, marker in [
        ('package', 'test', ['//scenarios:package_test'], 'SOURCE_SDK_PACKAGE=42'),
        ('razor', 'test', ['//scenarios:razor_test'], '<p>source SDK razor</p>'),
        ('publish', 'build', ['//scenarios:publish'], None),
    ]:
        result = subprocess.run(base + [command, *targets, '--jobs=2', '--lockfile_mode=off'] +
                                (['--test_output=all'] if command == 'test' else []), cwd=w,
                                capture_output=True, text=True, timeout=600)
        output = result.stdout + result.stderr
        (folder / (case + '.log')).write_text(output)
        assert result.returncode == 0 and (marker is None or marker in output), output[-7000:]
        reports.append({'case': case, 'exitCode': result.returncode})
        print(case, result.returncode, flush=True)
    published = w / 'bazel-bin/scenarios/publish.layout'
    result = subprocess.run([w / 'bazel-bin/produced_runtime.runtime/dotnet', published / 'Publish.dll'], capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.strip() == 'SOURCE_SDK_PUBLISH', result
    reports.append({'case': 'execute-published-app', 'output': result.stdout.strip()})
    (folder / 'scenarios-report.json').write_text(json.dumps(reports, indent=2) + '\n')
finally:
    subprocess.run(base + ['shutdown'], cwd=w, check=True)
