"""Package SDKs resolve from declared archives before offline Restore."""

import argparse
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared-restore', action='store_true', help='Linux stable-path preparation regression')
    args = parser.parse_args()
    assert not args.prepared_restore or os.uname().sysname == 'Linux'
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
            if args.prepared_restore:
                # Package-SDK bootstrap must leave Restore's environment key stable.
                (root / 'mapping.json').write_text(json.dumps({'projectDefaults': {'preparedRestore': True}}))
                prepared = authored.replace('projects=["App/App.csproj"]', 'projects=["App/App.csproj"],mappings="mapping.json"')
                (root / 'BUILD.bazel').write_text(prepared)
                bazel('run', '//:sync')
                bazel('run', '//:sync', '--', '--check')
                assert json.loads((root / 'graph.generated.json').read_text())['Restore']
                (root / 'BUILD.bazel').write_text(prepared + 'load(":graph.generated.bzl","app_graph")\napp_graph(name="graph",linux_stable_paths=True)\nmsbuild_graph_binary(name="app",graph=":graph",project="App/App.csproj")\n')
                assert '\ndeclared SDK\n' in bazel('run', '//:app')
                assert json.loads((root / 'bazel-bin/graph.graph/report.json').read_text())['preparedRestore']
                (root / 'App/Code.cs').write_text((root / 'App/Code.cs').read_text().replace('declared SDK', 'edited SDK'))
                events = base / 'body.bep'
                assert '\nedited SDK\n' in bazel('run', '//:app', '--build_event_json_file=' + str(events))
                metrics = next(json.loads(line)['buildMetrics']['actionSummary'] for line in events.read_text().splitlines() if 'buildMetrics' in json.loads(line))
                preparations = sum(int(row.get('actionsExecuted', 0)) for row in metrics.get('actionData', []) if row['mnemonic'] == 'MSBuildGraphRestore')
                assert preparations == 0, 'A body edit must reuse package-SDK Restore'
                assert (root / 'NuGet.Config').read_text() == config
                assert (root / 'bazel-bin/graph.graph/workspace/App/bin/Release/net10.0/NuGet.Config').read_text() == config
            # Even after a successful run, missing declared SDKs cannot use a warm host cache.
            (root / 'BUILD.bazel').write_text(authored.replace('packages=[":sdk"]', 'packages=[]'))
            assert 'Fixture.Sdk' in bazel('run', '//:sync', success=False)
            print('PASS: offline package SDK sync/build, authored config preservation and missing-closure rejection'
                  + ('; prepared Restore/body reuse' if args.prepared_restore else ''))
        finally:
            bazel('shutdown')


if __name__ == '__main__':
    main()
