"""Pack preserves PrivateAssets and an independent offline consumer sees public APIs."""

import json
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from qualify import DOTNET, RUNNER, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-private-assets-') as temporary:
        directory = Path(temporary).resolve()
        feed = directory / 'feed'
        feed.mkdir()
        # Distinct assemblies make visibility checks independent of nuspec metadata.
        for name, value in [('PublicDependency', 7), ('PrivateDependency', 99), ('SelectiveDependency', 23)]:
            package = directory / name
            package.mkdir()
            project = package / (name + '.csproj')
            project.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                '<TargetFramework>net11.0</TargetFramework></PropertyGroup></Project>')
            (package / 'Code.cs').write_text(f'public static class {name} {{ public static int Value => {value}; }}')
            run(DOTNET, 'pack', project, '-c', 'Release', '-o', feed,
                f'-p:RestoreSources={feed}', '-p:NuGetAudit=false', '-p:UseSharedCompilation=false')
        root = directory / 'producer'
        root.mkdir()
        (root / '.package-source').mkdir()
        for archive in feed.glob('*.nupkg'):
            shutil.copyfile(archive, root / '.package-source' / archive.name)
        project = root / 'Library.csproj'
        project.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFramework>net11.0</TargetFramework></PropertyGroup><ItemGroup>'
            '<PackageReference Include="PublicDependency" Version="1.0.0" />'
            '<PackageReference Include="PrivateDependency" Version="1.0.0" PrivateAssets="all" />'
            '<PackageReference Include="SelectiveDependency" Version="1.0.0" PrivateAssets="compile" />'
            '</ItemGroup></Project>')
        (root / 'Code.cs').write_text('public static class Library { public static int Value => PublicDependency.Value; '
            'public static string PrivateName => nameof(PrivateDependency); }')
        manifest = directory / 'producer.json'
        manifest.write_text(json.dumps({'Version': 1, 'Entry': 'Library.csproj', 'SdkVersion': '11.0.100',
            'Properties': {'Configuration': 'Release'}, 'SharedInputs': [],
            'Projects': {'Library.csproj': {'Inputs': ['Library.csproj', 'Code.cs'],
                'OutputDirectories': ['bin/Release/net11.0', 'obj/Release/net11.0'],
                'OutputFiles': ['bin/Release/Library.1.0.0.nupkg']}}}))
        report = directory / 'report.json'
        archive = root / 'bin/Release/Library.1.0.0.nupkg'

        def dependencies(path):
            with zipfile.ZipFile(path) as package:
                spec = ET.fromstring(package.read(next(n for n in package.namelist() if n.endswith('.nuspec'))))
                return {node.attrib['id']: dict(node.attrib) for node in spec.iter()
                        if node.tag.rsplit('}', 1)[-1] == 'dependency'}

        run(DOTNET, RUNNER, 'action', root, manifest, report, directory / 'cache', 'Pack')
        assert json.loads(report.read_text())['misses'] == 1
        metadata = dependencies(archive)
        assert set(metadata) == {'PublicDependency', 'SelectiveDependency'}, metadata
        assert all(item['version'] == '1.0.0' for item in metadata.values()), metadata
        assert set(metadata['PublicDependency']['exclude'].split(',')) == {'Build', 'Analyzers'}, metadata
        assert set(metadata['SelectiveDependency']['include'].split(',')) == {
            'Runtime', 'Build', 'Native', 'ContentFiles', 'Analyzers', 'BuildTransitive'}, metadata
        assert 'exclude' not in metadata['SelectiveDependency'], metadata
        packed = archive.read_bytes()
        # Clean outputs and recover the Pack snapshot, including its declared archive.
        shutil.rmtree(root / 'bin')
        shutil.rmtree(root / 'obj/Release')
        run(DOTNET, RUNNER, 'action', root, manifest, report, directory / 'cache', 'Pack')
        assert json.loads(report.read_text())['hits'] == 1
        assert archive.read_bytes() == packed
        # Raw SDK Pack provides a metadata parity control using an independent package cache.
        raw = directory / 'raw'
        raw.mkdir()
        for name in ['Library.csproj', 'Code.cs']:
            shutil.copyfile(root / name, raw / name)
        run(DOTNET, 'pack', raw / 'Library.csproj', '-c', 'Release', '-o', raw / 'packages',
            f'-p:RestoreSources={feed}', f'-p:RestorePackagesPath={raw / "nuget"}',
            '-p:NuGetAudit=false', '-p:UseSharedCompilation=false')
        assert dependencies(raw / 'packages/Library.1.0.0.nupkg') == dependencies(archive)
        # Export only the package and flowing dependencies. Neither producer outputs nor
        # private archive are available to the consumer's empty package cache.
        consumer = directory / 'consumer'
        consumer.mkdir()
        consumer_feed = consumer / 'feed'
        consumer_feed.mkdir()
        shutil.copyfile(archive, consumer_feed / archive.name)
        for name in ['PublicDependency', 'SelectiveDependency']:
            shutil.copyfile(feed / f'{name}.1.0.0.nupkg', consumer_feed / f'{name}.1.0.0.nupkg')
        # Remove all producer sources and feeds before consuming the exported packages.
        for path in [root, raw, feed, directory / 'PublicDependency', directory / 'PrivateDependency', directory / 'SelectiveDependency']:
            shutil.rmtree(path)
        config = consumer / 'NuGet.Config'
        config.write_text('<configuration><packageSources><clear/><add key="offline" value="feed"/>'
            '</packageSources><fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>')
        app = consumer / 'App.csproj'
        app.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net11.0</TargetFramework>'
            '<OutputType>Exe</OutputType></PropertyGroup><ItemGroup>'
            '<PackageReference Include="Library" Version="1.0.0" /></ItemGroup></Project>')
        code = consumer / 'Program.cs'
        code.write_text('if (Library.PrivateName != "PrivateDependency") throw new System.Exception(); '
            'if ((int)System.Reflection.Assembly.Load("SelectiveDependency").GetType("SelectiveDependency")'
            '.GetProperty("Value").GetValue(null) != 23) throw new System.Exception(); '
            'System.Console.WriteLine(Library.Value + PublicDependency.Value);')
        run(DOTNET, 'restore', app, '--configfile', config, '--packages', consumer / 'nuget', '-p:NuGetAudit=false')
        assets = json.loads((consumer / 'obj/project.assets.json').read_text())
        assert set(assets['libraries']) == {'Library/1.0.0', 'PublicDependency/1.0.0', 'SelectiveDependency/1.0.0'}, assets['libraries']
        target = next(iter(assets['targets'].values()))
        assert 'lib/net11.0/PublicDependency.dll' in target['PublicDependency/1.0.0']['compile']
        selective = target['SelectiveDependency/1.0.0']
        assert 'lib/net11.0/SelectiveDependency.dll' not in selective.get('compile', {}), selective
        assert 'lib/net11.0/SelectiveDependency.dll' in selective['runtime'], selective
        run(DOTNET, 'build', app, '-c', 'Release', '--no-restore', '-p:UseSharedCompilation=false')
        assert (consumer / 'bin/Release/net11.0/SelectiveDependency.dll').is_file()
        assert run(DOTNET, consumer / 'bin/Release/net11.0/App.dll').stdout.strip() == '14'
        assert not (consumer / 'bin/Release/net11.0/PrivateDependency.dll').exists()
        for name in ['PrivateDependency', 'SelectiveDependency']:
            code.write_text(f'System.Console.WriteLine({name}.Value);')
            failure = run(DOTNET, 'build', app, '-c', 'Release', '--no-restore', '-p:UseSharedCompilation=false', success=False)
            assert 'CS0103' in failure.stdout and name in failure.stdout, failure.stdout
        print('PASS: graph Pack/replay and raw nuspec parity; offline consumer runs public dependency; private all and compile APIs rejected (CS0103), selective runtime retained')


if __name__ == '__main__':
    main()
