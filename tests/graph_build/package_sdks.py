"""Package SDKs resolve from declared archives before offline Restore."""

import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import zipfile

from qualify import ROOT


def main():
    with tempfile.TemporaryDirectory(prefix='graph-package-sdks-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        with zipfile.ZipFile(root / 'fixture.sdk.1.0.0.nupkg', 'w') as archive:
            archive.writestr('Fixture.Sdk.nuspec', '<package><metadata><id>Fixture.Sdk</id><version>1.0.0</version><authors>fixture</authors><description>fixture</description><packageTypes><packageType name="MSBuildSdk" /></packageTypes></metadata></package>')
            archive.writestr('sdk/Sdk.props', '<Project><PropertyGroup><DefineConstants>$(DefineConstants);PACKAGE_SDK</DefineConstants></PropertyGroup><ItemGroup><GlobalAnalyzerConfigFiles Include="$(MSBuildProjectDirectory)/../../missing.globalconfig" /></ItemGroup></Project>')
            archive.writestr('sdk/Sdk.targets', '<Project />')
        data = (root / 'fixture.sdk.1.0.0.nupkg').read_bytes()
        global_json = json.loads((ROOT / 'global.json').read_text())
        global_json['msbuild-sdks'] = {'Fixture.Sdk': '1.0.0', 'Unused.Sdk': '9.9.9'}
        (root / 'global.json').write_text(json.dumps(global_json))
        config = '<configuration><packageSources><clear /></packageSources></configuration>'
        (root / 'NuGet.Config').write_text(config)
        (root / 'App').mkdir()
        (root / 'App/App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><Import Project="Sdk.props" Sdk="Fixture.Sdk" /><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><Content Include="../NuGet.Config" Link="NuGet.Config" CopyToOutputDirectory="Always" /></ItemGroup></Project>')
        (root / 'App/Code.cs').write_text('#if PACKAGE_SDK\nSystem.Console.WriteLine("declared SDK");\n#else\n#error Missing package SDK\n#endif')
        (root / 'MODULE.bazel').write_text('module(name="package_sdks")\nbazel_dep(name="rules_msbuild",version="0.0.0")\n'
            f'local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})\n'
            'dotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\n'
            'dotnet.sdk(name="dotnet",global_json="//:global.json")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
        authored = ('load("@rules_msbuild//msbuild:defs.bzl","msbuild_nuget_package","msbuild_package_lock","msbuild_graph_binary")\n'
            'load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\n'
            f'msbuild_nuget_package(name="sdk",package_id="Fixture.Sdk",version="1.0.0",archive="fixture.sdk.1.0.0.nupkg",archive_sha256="{hashlib.sha256(data).hexdigest()}",content_hash="{base64.b64encode(hashlib.sha512(data).digest()).decode()}")\n'
            'msbuild_package_lock(name="packages",packages=[":sdk"])\n'
            'msbuild_sync(name="sync",mode="graph",package_build=True,package_lock=":packages",projects=["App/App.csproj"])\n')
        (root / 'BUILD.bazel').write_text(authored)
        prefix = [str(ROOT / 'scripts/bazel-launcher.sh'), f'--output_base={base / "bazel"}']
        def bazel(*args, success=True):
            result = subprocess.run(prefix + list(args), cwd=root, env=os.environ, text=True, capture_output=True, timeout=180)
            assert (result.returncode == 0) == success, result.stdout + result.stderr
            return result.stdout + result.stderr
        try:
            bazel('run', '//:sync')
            bazel('run', '//:sync', '--', '--check')
            (root / 'BUILD.bazel').write_text(authored + 'load(":graph.generated.bzl","app_graph")\napp_graph(name="graph")\nmsbuild_graph_binary(name="app",graph=":graph",project="App/App.csproj")\n')
            assert '\ndeclared SDK\n' in bazel('run', '//:app')
            assert (root / 'NuGet.Config').read_text() == config
            assert (root / 'bazel-bin/graph.graph/workspace/App/bin/Release/net10.0/NuGet.Config').read_text() == config
            # Even after a successful run, missing declared SDKs cannot use a warm host cache.
            (root / 'BUILD.bazel').write_text(authored.replace('packages=[":sdk"]', 'packages=[]'))
            assert 'Fixture.Sdk' in bazel('run', '//:sync', success=False)
            print('PASS: offline package SDK sync/build, unused SDK registry entry and missing-closure rejection')
        finally:
            bazel('shutdown')


if __name__ == '__main__':
    main()
