"""Public graph sync with locked transitive packages and selected configuration."""

import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

from qualify import DOTNET, ROOT, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-devex-') as temporary:
        directory = Path(temporary).resolve()
        workspace = directory / 'workspace'
        workspace.mkdir()
        archives = workspace / 'packages'
        archives.mkdir()
        for version, value in [('1.0.0', 11), ('2.0.0', 22)]:
            for name, source, reference in [
                ('Core', f'public static class Core {{ public static int Value => {value}; }}', ''),
                ('Api', 'public static class Api { public static int Value => Core.Value; }',
                 f'<ItemGroup><PackageReference Include="Core" Version="{version}" /></ItemGroup>'),
            ]:
                package = directory / (name + version)
                package.mkdir()
                project = package / (name + '.csproj')
                project.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>'
                                   f'<Version>{version}</Version></PropertyGroup>{reference}</Project>')
                (package / 'Code.cs').write_text(source)
                run(DOTNET, 'pack', project, '-o', archives, '-p:RestoreSources=' + str(archives),
                    '-p:NuGetAudit=false', '-p:UseSharedCompilation=false')
        shutil.copy(ROOT / 'global.json', workspace / 'global.json')
        (workspace / 'MODULE.bazel').write_text(
            'module(name="graph_devex")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n'
            f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})\n'
            'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
            'dotnet.sdk(name="dotnet",global_json="//:global.json")\n'
            'use_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
        app = workspace / 'App'
        app.mkdir()
        (app / 'Code.cs').write_text('#if DEBUG\nSystem.Console.WriteLine(Api.Value);\n#else\n#error Expected Debug\n#endif')
        prefix = [str(ROOT / 'scripts/bazel-launcher.sh'), f'--output_base={directory / "bazel"}']

        def bazel(*args, success=True):
            result = subprocess.run(prefix + list(args), cwd=workspace, env=os.environ, text=True, capture_output=True)
            assert (result.returncode == 0) == success, result.stdout + result.stderr
            return result.stdout + result.stderr

        def declarations(version, complete=True):
            text = 'load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package","msbuild_package_lock","msbuild_graph_binary")\n'
            text += 'load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\n'
            for name in ['Core', 'Api']:
                archive = archives / f'{name}.{version}.nupkg'
                data = archive.read_bytes()
                text += (f'msbuild_nuget_package(name="{name}",package_id="{name}",version="{version}",'
                         f'archive="packages/{archive.name}",archive_sha256="{hashlib.sha256(data).hexdigest()}",'
                         f'content_hash="{base64.b64encode(hashlib.sha512(data).digest()).decode()}",'
                         + ('deps=[":Core"]' if name == 'Api' and complete else '') + ')\n')
            text += 'msbuild_package_lock(name="packages",packages=[":Api"])\n'
            text += ('msbuild_sync(name="sync",mode="graph",projects=["App/App.csproj"],'
                     'configuration="Debug",framework="net10.0",package_lock=":packages")\n')
            return text

        try:
            for version, value in [('1.0.0', 11), ('2.0.0', 22)]:
                (app / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                    '<TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks><OutputType>Exe</OutputType></PropertyGroup>'
                    f'<ItemGroup><PackageReference Include="Api" Version="{version}" /></ItemGroup></Project>')
                authored = declarations(version)
                (workspace / 'BUILD.bazel').write_text(authored)
                bazel('run', '//:sync')
                bazel('run', '//:sync', '--', '--check')
                contract = json.loads((workspace / 'graph.generated.json').read_text())
                assert contract['Properties'] == {'Configuration': 'Debug', 'TargetFramework': 'net10.0'}
                assert len(contract['Projects']['App/App.csproj']['Configurations']) == 1
                (workspace / 'BUILD.bazel').write_text(authored +
                    'load(":graph.generated.bzl","app_graph")\napp_graph(name="graph")\n'
                    'msbuild_graph_binary(name="app",graph=":graph",project="App/App.csproj")\n')
                assert str(value) in bazel('run', '//:app').splitlines()
            # A graph feed may pin several versions, while each project resolves its own closure.
            other = workspace / 'Other'
            other.mkdir()
            (other / 'Other.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                '<TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup>'
                '<ItemGroup><PackageReference Include="Api" Version="1.0.0" /></ItemGroup></Project>')
            (other / 'Code.cs').write_text('System.Console.WriteLine(Api.Value);')
            old_packages = '\n'.join(line for line in declarations('1.0.0').splitlines() if line.startswith('msbuild_nuget_package('))
            old_packages = old_packages.replace('name="Core"', 'name="Core_v1"').replace('name="Api"', 'name="Api_v1"').replace('deps=[":Core"]', 'deps=[":Core_v1"]')
            multiple = declarations('2.0.0').replace('packages=[":Api"]', 'packages=[":Api",":Api_v1"],allow_multiple_versions=True').replace(
                'projects=["App/App.csproj"]', 'projects=["App/App.csproj","Other/Other.csproj"]') + old_packages + '\n'
            build_file = workspace / 'BUILD.bazel'
            build_file.write_text(multiple)
            bazel('run', '//:sync')
            graph_targets = ('load(":graph.generated.bzl","app_graph")\napp_graph(name="graph")\n'
                'msbuild_graph_binary(name="app",graph=":graph",project="App/App.csproj")\n'
                'msbuild_graph_binary(name="other",graph=":graph",project="Other/Other.csproj")\n')
            build_file.write_text(multiple + graph_targets)
            assert '22' in bazel('run', '//:app').splitlines()
            assert '11' in bazel('run', '//:other').splitlines()
            output = workspace / 'bazel-bin/graph.graph/workspace'
            for project, version in [('App', '2.0.0'), ('Other', '1.0.0')]:
                assets = json.loads((output / project / 'obj/project.assets.json').read_text())['libraries']
                assert 'Api/' + version in assets and 'Core/' + version in assets, assets
            project = other / 'Other.csproj'
            project.write_text(project.read_text().replace('Version="1.0.0"', 'Version="2.0.0"'))
            bazel('run', '//:sync')
            assert '22' in bazel('run', '//:other').splitlines()
            # Restore the single-project setup for the corruption and missing-closure controls.
            build_file.write_text(declarations('2.0.0'))
            bazel('run', '//:sync')
            build_file.write_text(declarations('2.0.0') + graph_targets.replace(
                'msbuild_graph_binary(name="other",graph=":graph",project="Other/Other.csproj")\n', ''))
            # Graph consumers must retain the package provider's hash verification.
            build_file = workspace / 'BUILD.bazel'
            valid_build = build_file.read_text()
            digest = hashlib.sha256((archives / 'Api.2.0.0.nupkg').read_bytes()).hexdigest()
            build_file.write_text(valid_build.replace(digest, '0' * 64))
            assert 'Package archive differs from locked archive hash' in bazel('build', '//:graph', success=False)
            build_file.write_text(valid_build)
            # An incomplete transitive closure cannot use the host package cache.
            (workspace / 'BUILD.bazel').write_text(declarations('2.0.0', complete=False) +
                'load(":graph.generated.bzl","app_graph")\napp_graph(name="graph")\n')
            failure = bazel('build', '//:graph', success=False)
            assert 'Graph package set changed' in failure, failure
            bazel('run', '//:sync')
            # A caller's NuGet.Config feed cannot fill the lock gap.
            (workspace / 'NuGet.Config').write_text('<configuration><packageSources><add key="ambient" value="' + str(archives) + '"/></packageSources></configuration>')
            failure = bazel('build', '//:graph', success=False)
            assert 'NU1101' in failure or 'NU1102' in failure, failure
            # Imported package behavior must not silently enter a source-only contract.
            archive = archives / 'Api.2.0.0.nupkg'
            with zipfile.ZipFile(archive, 'a') as package:
                package.writestr('buildTransitive/Api.props', '<Project><PropertyGroup><DefineConstants>$(DefineConstants);PACKAGE_BUILD</DefineConstants></PropertyGroup></Project>')
                package.writestr('buildTransitive/Api.targets', '''<Project>
<ItemGroup><Content Include="$(MSBuildThisFileDirectory)message.txt" Link="message.txt" CopyToOutputDirectory="PreserveNewest" /></ItemGroup>
<Target Name="GeneratePackageCode" BeforeTargets="CoreCompile">
<Error Condition="!Exists('$(MSBuildProjectDirectory)/../shared/value.txt')" Text="Missing declared package input value.txt"/>
<ReadLinesFromFile File="$(MSBuildProjectDirectory)/../shared/value.txt"><Output TaskParameter="Lines" PropertyName="GeneratedValue"/></ReadLinesFromFile>
<WriteLinesToFile File="$(IntermediateOutputPath)Package.g.cs" Lines="public static class Generated { public static int Value =&gt; $(GeneratedValue)%3B }" Overwrite="true"/>
<ItemGroup><Compile Include="$(IntermediateOutputPath)Package.g.cs" /></ItemGroup>
</Target></Project>''')
                package.writestr('buildTransitive/message.txt', 'package-content')
            (workspace / 'BUILD.bazel').write_text(declarations('2.0.0'))
            failure = bazel('run', '//:sync', success=False)
            assert 'build/content assets' in failure, failure
            (workspace / 'shared').mkdir()
            (workspace / 'shared/value.txt').write_text('42')
            (app / 'Code.cs').write_text('#if !PACKAGE_BUILD\n#error Missing restored package props\n#endif\nSystem.Console.WriteLine(Generated.Value); System.Console.WriteLine(System.IO.File.ReadAllText("message.txt"));')
            authored = declarations('2.0.0').replace('mode="graph",', 'mode="graph",package_build=True,package_inputs=["shared/value.txt"],')
            (workspace / 'BUILD.bazel').write_text(authored)
            before = {str(p.relative_to(app)): p.read_bytes() for p in app.rglob('*') if p.is_file()}
            bazel('run', '//:sync')
            bazel('run', '//:sync', '--', '--check')
            assert before == {str(p.relative_to(app)): p.read_bytes() for p in app.rglob('*') if p.is_file()}
            (workspace / 'BUILD.bazel').write_text(authored +
                'load(":graph.generated.bzl","app_graph")\napp_graph(name="graph")\n'
                'msbuild_graph_binary(name="app",graph=":graph",project="App/App.csproj")\n')
            output = bazel('run', '//:app')
            assert '42' in output.splitlines() and 'package-content' in output.splitlines(), output
            (workspace / 'shared/value.txt').write_text('43')
            assert '43' in bazel('run', '//:app').splitlines()
            # Task-only reads must be declared rather than borrowing the checkout.
            (workspace / 'BUILD.bazel').write_text((workspace / 'BUILD.bazel').read_text().replace('package_inputs=["shared/value.txt"],', ''))
            bazel('run', '//:sync')
            failure = bazel('build', '//:graph', success=False)
            assert 'value.txt' in failure, failure
            print('PASS: multi-version project selection and upgrade, package props, generated source/content, task-input edit/rejection, package pinning and configuration')
        finally:
            bazel('shutdown')


if __name__ == '__main__':
    main()
