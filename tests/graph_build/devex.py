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
            failure = bazel('build', '//:graph', success=False)
            assert 'NU1101' in failure or 'NU1102' in failure, failure
            # Imported package behavior must not silently enter a source-only contract.
            archive = archives / 'Api.2.0.0.nupkg'
            with zipfile.ZipFile(archive, 'a') as package:
                package.writestr('buildTransitive/Api.targets', '<Project/>')
            (workspace / 'BUILD.bazel').write_text(declarations('2.0.0'))
            failure = bazel('run', '//:sync', success=False)
            assert 'build/content assets' in failure, failure
            print('PASS: locked transitive packages, Debug/framework selection, upgrade, missing closure and build-asset rejection')
        finally:
            bazel('shutdown')


if __name__ == '__main__':
    main()
