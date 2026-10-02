"""Check dependency-order measurements on chains, diamonds and configured coordinators."""

import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-dependency-order-') as temporary:
        base = Path(temporary).resolve()
        driver = base / 'driver'
        driver.mkdir()
        upstream = ROOT / 'tests/graph_build/upstream'
        shutil.copyfile(upstream / 'RuntimeRawGraph.cs.txt', driver / 'Program.cs')
        shutil.copyfile(upstream / 'RuntimeRawGraph.csproj.txt', driver / 'Raw.csproj')
        run(DOTNET, 'build', driver / 'Raw.csproj', '-c', 'Release', '-p:UseSharedCompilation=false', '-p:NuGetAudit=false')
        for shape, transitive in [('chain', False), ('chain', True), ('diamond', False), ('diamond', True), ('configured', True)]:
            root = base / (shape + str(transitive))
            root.mkdir()
            contract = fixture(root, 4 if shape == 'diamond' else 3)
            contract['Properties']['DisableTransitiveProjectReferences'] = str(not transitive).lower()
            for project in contract['Projects'].values():
                project['ReferenceBoundary'] = True
            if shape == 'diamond':
                project = root / 'P2/P2.csproj'
                project.write_text(project.read_text().replace('../P1/P1.csproj', '../P0/P0.csproj'))
                source = root / 'P2/Code.cs'
                source.write_text(source.read_text().replace('P1.Value()', 'P0.Value()'))
                project = root / 'P3/P3.csproj'
                project.write_text(project.read_text().replace('</Project>', '<ItemGroup><ProjectReference Include="../P1/P1.csproj" /></ItemGroup></Project>'))
            if shape == 'configured':
                project = root / 'P0/P0.csproj'
                project.write_text(project.read_text().replace('<TargetFramework>net10.0</TargetFramework>',
                                  '<TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks>'))
                contract['Version'] = 2
                contract['Entries'] = ['P0/P0.csproj', 'P2/P2.csproj']
                producer = contract['Projects']['P0/P0.csproj']
                producer['OutputDirectories'] = []
                producer['ReferenceBoundary'] = False
                producer['Configurations'] = [{'Properties': {'TargetFramework': framework}, 'Inputs': [],
                    'ReferenceBoundary': bool(framework), 'OutputDirectories':
                    [f'P0/bin/Release/{framework}', f'P0/obj/Release/{framework}'] if framework else []}
                    for framework in ['', 'net10.0', 'net10.0-windows']]
            manifest = root / 'contract.json'
            manifest.write_text(json.dumps(contract))
            report = base / (root.name + '.json')
            run(DOTNET, driver / 'bin/Release/net10.0/Raw.dll', root, manifest, 'dependency-order', report)
            result = json.loads(report.read_text())
            assert result['orderEqual'], result
            if shape == 'configured':
                assert result['configuredNodes'] == 5 and result['compiledNodes'] == 4 and result['coordinatorConsumers'] > 0, result
            else:
                expected = {'chain': (5, 6), 'diamond': (9, 10)}[shape][transitive]
                assert result['orderedRecords'] == expected, result
            print(f'PASS: {shape}, transitive={transitive}, identical configured-node ordering')


if __name__ == '__main__':
    main()
