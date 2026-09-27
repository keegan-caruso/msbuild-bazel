"""Qualify packages, Razor rendering, and framework-dependent publish with a produced SDK.

Run after generated_sdk.py --archive, against that fixture's workspace/toolchain.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('directory', type=Path)
a = parser.parse_args()
folder = a.directory.resolve()
w = folder / 'source'
assert (w / 'source-sdk.tar.gz').is_file(), 'Run the archive SDK fixture first'


def put(name, text):
    path = w / 'scenarios' / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


put('Package.csproj', '''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><PackageId>SourceSdk.Package</PackageId><Version>1.0.0</Version><PackageOutputPath>$(BaseIntermediateOutputPath)packages/</PackageOutputPath></PropertyGroup><Target Name="ExportPackage" DependsOnTargets="Pack"><Copy SourceFiles="$(PackageOutputPath)SourceSdk.Package.1.0.0.nupkg" DestinationFiles="$(PackageArchive)" /></Target></Project>''')
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
put('Publish.csproj', '''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><UseAppHost>false</UseAppHost><PublishDir>$(BaseIntermediateOutputPath)publish/</PublishDir></PropertyGroup><Target Name="ExportPublish" DependsOnTargets="Publish"><ZipDirectory SourceDirectory="$(PublishDir)" DestinationFile="$(PublishedArchive)" Overwrite="true" /></Target></Project>''')
put('Publish.cs', 'System.Console.WriteLine("SOURCE_SDK_PUBLISH");')
put('BUILD.bazel', '''load("@rules_msbuild//msbuild:defs.bzl","msbuild_generate","msbuild_generated_nuget_package","msbuild_package_lock","msbuild_test","msbuild_library","msbuild_items")
msbuild_generate(name="pack",project="Package.csproj",srcs=["Value.cs"],target_framework="net10.0",targets=["ExportPackage"],outputs=["SourceSdk.Package.1.0.0.nupkg"],output_properties={"PackageArchive":"SourceSdk.Package.1.0.0.nupkg"})
msbuild_generated_nuget_package(name="package",package_id="SourceSdk.Package",version="1.0.0",archive=":pack")
msbuild_package_lock(name="lock",packages=[":package"])
msbuild_test(name="package_test",project="PackageApp.csproj",srcs=["PackageApp.cs"],target_framework="net10.0",package_lock=":lock",deps=[":package"],use_apphost=False)
msbuild_items(name="view",item_type="RazorGenerate",srcs=["Views/Hello.cshtml"],metadata={"Link":"Views/Hello.cshtml"})
msbuild_library(name="views",project="Views.csproj",srcs=["Marker.cs"],target_framework="net10.0",items=[":view"],framework_refs=["Microsoft.AspNetCore.App"])
msbuild_test(name="razor_test",project="RazorApp.csproj",srcs=["RazorApp.cs"],target_framework="net10.0",deps=[":views"],framework_refs=["Microsoft.AspNetCore.App"],use_apphost=False)
msbuild_generate(name="publish",executable=True,project="Publish.csproj",srcs=["Publish.cs"],target_framework="net10.0",targets=["ExportPublish"],outputs=["published.zip"],output_properties={"PublishedArchive":"published.zip"},use_apphost=False)
''')
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
    published = folder / 'published'
    with zipfile.ZipFile(w / 'bazel-bin/scenarios/publish.generated/published.zip') as archive:
        archive.extractall(published)
    result = subprocess.run([w / 'bazel-bin/artifacts/dotnet', published / 'Publish.dll'], capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.strip() == 'SOURCE_SDK_PUBLISH', result
    reports.append({'case': 'execute-published-app', 'output': result.stdout.strip()})
    (folder / 'scenarios-report.json').write_text(json.dumps(reports, indent=2) + '\n')
finally:
    subprocess.run(base + ['shutdown'], cwd=w, check=True)
