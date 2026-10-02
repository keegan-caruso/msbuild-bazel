"""Offline package compilation, buildTransitive generation, replay and upgrades."""

import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, RUNNER, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-packages-') as temporary:
        directory = Path(temporary).resolve()
        package = directory / 'package'
        package.mkdir()
        (package / 'empty').mkdir()
        (package / 'Fixture.Tools.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFramework>net10.0</TargetFramework><PackageId>Fixture.Tools</PackageId>'
            '</PropertyGroup><ItemGroup><None Include="Fixture.Tools.targets" Pack="true" '
            'PackagePath="buildTransitive/" /></ItemGroup></Project>')
        (package / 'Fixture.Tools.targets').write_text('''<Project>
<Target Name="GeneratePackageSource" BeforeTargets="CoreCompile">
<WriteLinesToFile File="$(IntermediateOutputPath)Package.g.cs" Overwrite="true"
 Lines="public static class GeneratedApi { public static int Extra =&gt; 3%3B }" />
<ItemGroup><Compile Include="$(IntermediateOutputPath)Package.g.cs" /></ItemGroup>
</Target></Project>''')
        archives = directory / 'archives'
        for version, value in [('1.0.0', 7), ('2.0.0', 8)]:
            (package / 'Code.cs').write_text(f'public static class PackageApi {{ public static int Value => {value}; }}')
            run(DOTNET, 'pack', package / 'Fixture.Tools.csproj', '-c', 'Release', '-o', archives,
                f'-p:Version={version}', f'-p:RestoreSources={package / "empty"}',
                '-p:NuGetAudit=false', '-p:UseSharedCompilation=false')
        root = directory / 'workspace'
        manifest = directory / 'contract.json'
        report = directory / 'report.json'
        cache = directory / 'snapshots'
        manifest.write_text(json.dumps({'Version': 1, 'Entry': 'App.csproj', 'SdkVersion': '10.0.400',
            'Properties': {'Configuration': 'Release'}, 'SharedInputs': [],
            'Projects': {'App.csproj': {'Inputs': ['App.csproj', 'Program.cs'],
                                      'OutputDirectories': ['bin/Release/net10.0', 'obj/Release/net10.0']}}}))

        def build(version, expected, selected_cache=cache):
            if root.exists():
                shutil.rmtree(root)
            root.mkdir()
            source = root / '.package-source'
            source.mkdir()
            shutil.copyfile(archives / f'Fixture.Tools.{version}.nupkg', source / f'Fixture.Tools.{version}.nupkg')
            (root / 'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                '<TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup>'
                f'<ItemGroup><PackageReference Include="Fixture.Tools" Version="{version}" /></ItemGroup></Project>')
            (root / 'Program.cs').write_text('System.Console.WriteLine(PackageApi.Value + GeneratedApi.Extra);')
            run(DOTNET, RUNNER, 'action', root, manifest, report, selected_cache)
            assert run(DOTNET, root / 'bin/Release/net10.0/App.dll').stdout.strip() == str(expected)
            assert (root / 'obj/Release/net10.0/Package.g.cs').is_file()
            assert (root / 'bin/Release/net10.0/Fixture.Tools.dll').is_file()
            return json.loads(report.read_text()), {str(p.relative_to(root)): p.read_bytes()
                for path in [root / 'bin/Release', root / 'obj/Release'] for p in path.rglob('*')
                if p.is_file() and not p.name.endswith('.AssemblyReference.cache')}

        base, _ = build('1.0.0', 10)
        replay, _ = build('1.0.0', 10)
        assert base['misses'] == 1 and replay['hits'] == 1
        upgrade, outputs = build('2.0.0', 11)
        recovered, recovered_outputs = build('2.0.0', 11)
        control, control_outputs = build('2.0.0', 11, directory / 'control')
        assert upgrade['misses'] == 1 and recovered['hits'] == 1 and control['misses'] == 1
        assert outputs == recovered_outputs == control_outputs
        print('PASS: offline package assembly, buildTransitive generation, clean replay, upgrade, fresh output parity')


if __name__ == '__main__':
    main()
