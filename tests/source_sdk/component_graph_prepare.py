"""Prepare the SBRP -> Arcade -> CommandLine qualification graph.

Each source archive contains its own implementation, shared Arcade scripts, and
VMR/project metadata. This selector is qualified only for these three components.
"""
import argparse
import json
import os
from pathlib import Path
import shutil

from component_sources import select


def script(component, dependencies):
    projects = ';'.join('/source/repo-projects/' + name + '.proj' for name in dependencies)
    common = '--configuration Release --arch arm64 --official-build-id 20251023.11 --branding rtm /p:Publish=false --source-repository https://github.com/dotnet/dotnet --source-version b0f34d51fccc69fd334253924abd8d6853fad7aa'
    extraction = ''
    if dependencies:
        extraction = f'''cat > extract-dependency-tools.proj <<'XML'
<Project>
  <Target Name="Restore"><MSBuild Projects="{projects}" Targets="Restore" Properties="BuildProjectReferences=false" BuildInParallel="false" /></Target>
  <Target Name="Build"><MSBuild Projects="{projects}" Targets="ExtractToolPackage" Properties="BuildProjectReferences=false" BuildInParallel="false" /></Target>
</Project>
XML
./build.sh -sb --projects /source/extract-dependency-tools.proj {common} > dependency-tools.log 2>&1 || {{ tail -100 dependency-tools.log; exit 1; }}
'''
    patch = 'patch -p1 < identitymodel.patch' if component == 'source-build-reference-packages' else ''
    extra = '--extra-tree prereqs/packages/reference' if component == 'source-build-reference-packages' else ''
    return f'''set -euo pipefail
export DOTNET_PROCESSOR_COUNT=1 DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_GENERATE_ASPNET_CERTIFICATE=false NuGetAudit=false
{patch}
./prep-source-build.sh --no-sdk --no-bootstrap --no-artifacts --no-prebuilts > preparation.log 2>&1 || {{ tail -100 preparation.log; exit 1; }}
if [ -d /tmp/component-inputs ]; then cp -a /tmp/component-inputs/. /source/; fi
./build.sh -sb --projects /source/eng/tools/tasks/Microsoft.DotNet.UnifiedBuild.Tasks/Microsoft.DotNet.UnifiedBuild.Tasks.csproj {common} > utility-build.log 2>&1 || {{ tail -100 utility-build.log; exit 1; }}
{extraction}
/usr/bin/time -v -o build.time ./build.sh -sb --projects /source/repo-projects/{component}.proj {common} /p:BuildProjectReferences=false /p:BuildInParallel=false > build.log 2>&1 || {{ tail -120 build.log; exit 1; }}
mkdir result
python3 .qualification/component_outputs.py /source {component} result/component.tar {extra}
tar -cf result.tar *.log build.time result/component.json artifacts/log artifacts/obj/manifests/Release/{component}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source_action', type=Path)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    root, work = args.source_action.resolve(), args.directory.resolve()
    work.mkdir(parents=True, exist_ok=False)
    for name in ['native.tar', 'bootstrap.tar', 'bwrap', 'Driver.csproj']:
        os.link(root / name, work / name)
    shutil.copyfile(here.parents[1] / 'tests/explicit_msbuild/runtime/NativeBuild.cs.txt', work / 'Driver.cs')
    for name in ['source_action.bzl', 'component_action.bzl']:
        shutil.copyfile(here / name, work / name)
    module = (root / 'MODULE.bazel').read_text()
    module = '\n'.join(line for line in module.splitlines() if 'register_toolchains(' not in line)
    (work / 'MODULE.bazel').write_text(module + '\nregister_toolchains("@controller//:all")\n')
    nodes = {'source-build-reference-packages': [], 'arcade': ['source-build-reference-packages'], 'command-line-api': ['source-build-reference-packages', 'arcade']}
    helpers = [here / name for name in ['component_outputs.py', 'inventory.py', 'source_action_prepare.py']]
    build = ['load(":source_action.bzl", "native_driver")', 'load(":component_action.bzl", "source_component", "component_package")',
             'load("@rules_msbuild//msbuild:defs.bzl", "msbuild_generated_nuget_package", "msbuild_package_lock", "msbuild_test")',
             'native_driver(name="driver",driver_sdk="@controller//:sdk_host",driver_project="Driver.csproj",driver_source="Driver.cs")']
    for name, dependencies in nodes.items():
        select(root / 'sources.tar', name, work / (name + '.tar'), helpers)
        (work / (name + '.sh')).write_text(script(name, dependencies))
        build.append('source_component(name=%s,driver=":driver",sources=%s,script=%s,deps=%s,native_tools="native.tar",bootstrap="bootstrap.tar",sandbox="bwrap",exec_compatible_with=["@platforms//os:linux","@platforms//cpu:aarch64"])' %
                     (json.dumps(name), json.dumps(name + '.tar'), json.dumps(name + '.sh'), json.dumps([':' + item for item in dependencies])))
    build.extend([
        'component_package(name="commandline_archive",component=":command-line-api",member="artifacts/packages/Release/Shipping/command-line-api/System.CommandLine.2.0.0.nupkg")',
        'msbuild_generated_nuget_package(name="package",package_id="System.CommandLine",version="2.0.0",archive=":commandline_archive")',
        'msbuild_package_lock(name="lock",packages=[":package"])',
        'msbuild_test(name="consumer",project="App.csproj",srcs=["App.cs"],package_lock=":lock",deps=[":package"],target_framework="net10.0",use_apphost=False)',
    ])
    (work / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="System.CommandLine" Version="2.0.0" /></ItemGroup></Project>')
    (work / 'App.cs').write_text('var command = new System.CommandLine.RootCommand("qualification"); System.Console.WriteLine(command.Options.Count); return command.Options.Count == 2 ? 0 : 1;')
    (work / 'BUILD.bazel').write_text('\n'.join(build) + '\n')
    print(work, flush=True)


if __name__ == '__main__':
    main()
