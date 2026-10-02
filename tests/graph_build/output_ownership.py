"""Indexed ownership preserves the previous overlap and lookup policy."""
import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-output-ownership-') as temporary:
        base = Path(temporary).resolve()
        shutil.copyfile(ROOT / 'tests/graph_build/OutputOwnership.cs.txt', base / 'Program.cs')
        (base / 'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings>'
            '<Nullable>enable</Nullable></PropertyGroup><ItemGroup>'
            f'<Compile Include="{ROOT}/tools/GraphBuild/OutputOwnership.cs" /></ItemGroup></Project>')
        run(DOTNET, 'build', base / 'Probe.csproj', '-c', 'Release', '-p:UseSharedCompilation=false', '-warnaserror')
        print(run(DOTNET, base / 'bin/Release/net10.0/Probe.dll').stdout.strip())
        root = base / 'workspace'
        root.mkdir()
        fixture(root, 4)
        project = root / 'P2/P2.csproj'
        project.write_text(project.read_text().replace('../P1/P1.csproj', '../P0/P0.csproj'))
        source = root / 'P2/Code.cs'
        source.write_text(source.read_text().replace('P1.Value()', 'P0.Value()'))
        project = root / 'P3/P3.csproj'
        project.write_text(project.read_text().replace('</Project>', '<ItemGroup><ProjectReference Include="../P1/P1.csproj" /></ItemGroup></Project>'))
        props = root / 'Directory.Build.props'
        props.write_text(props.read_text().replace('</PropertyGroup>', '<DisableTransitiveProjectReferences>true</DisableTransitiveProjectReferences></PropertyGroup>'))
        run(DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root, SDK / 'sdk/10.0.400', 'P3/P3.csproj', '--graph')
        manifest = root / 'graph.generated.json'
        contract = json.loads(manifest.read_text())
        report = base / 'report.json'

        def clear():
            for project in contract['Projects'].values():
                for path in project['Configurations'][0]['OutputDirectories']:
                    shutil.rmtree(root / path, ignore_errors=True)

        def products():
            return {str(path.relative_to(root)): path.read_bytes() for directory in root.glob('P*')
                    for path in directory.glob('bin/Release/net10.0/*') if path.suffix in ['.dll', '.pdb']}

        for case, code, misses in [('seed', '=> 1;', 4), ('body', '=> 2;', 1),
                                   ('api', '=> 2; public static int Added() => 3;', 3)]:
            (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() ' + code + ' }')
            clear()
            run(DOTNET, RUNNER, 'action', root, manifest, report, base / 'cache')
            result = json.loads(report.read_text())
            assert result['misses'] == misses and result['hits'] == 4 - misses, result
            cached = products()
            clear()
            run(DOTNET, 'msbuild', root / 'P3/P3.csproj', '-graphBuild', '-m:4', '-t:Build',
                '-p:Configuration=Release', '-p:UseSharedCompilation=false', '-p:DisableTransitiveProjectReferences=true',
                '-p:NetCoreSdkRoot=' + str(SDK / 'sdk/10.0.400'),
                '-p:PathMap=' + str(root) + '=/_/workspace%2C' + str(SDK) + '=/_/sdk')
            assert products() == cached, case
        print('PASS: diamond seed/body/API raw compiler-output parity and expected cache boundaries')


if __name__ == '__main__':
    main()
