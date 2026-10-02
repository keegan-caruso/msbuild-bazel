"""Authored compile aliases and non-copying project references survive graph replay."""

import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-reference-roles-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        fixture(root)
        props = root / 'Directory.Build.props'
        props.write_text(props.read_text().replace('</PropertyGroup>',
            '<DisableTransitiveProjectReferences>true</DisableTransitiveProjectReferences></PropertyGroup>'))
        reference = root / 'P1/P1.csproj'
        reference.write_text(reference.read_text().replace('Include="../P0/P0.csproj"',
            'Include="../P0/P0.csproj" Aliases="Hidden" Private="false"'))
        (root / 'P0/Code.cs').write_text('public class P0 { public const int Value = 1; }')
        (root / 'P1/Code.cs').write_text('extern alias Hidden; public class P1 { public static int Value() => Hidden::P0.Value; }')
        run(DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll',
            root, SDK / 'sdk/10.0.400', 'P2/P2.csproj', '--graph')
        contract = root / 'graph.generated.json'
        report = base / 'report.json'

        def build(value, hits):
            for index in range(3):
                for folder in ['bin', 'obj']:
                    shutil.rmtree(root / f'P{index}' / folder, ignore_errors=True)
            run(DOTNET, RUNNER, 'action', root, contract, report, base / 'cache')
            assert json.loads(report.read_text())['hits'] == hits, report.read_text()
            output = root / 'P2/bin/Release/net10.0'
            assert not (output / 'P0.dll').exists()
            assert not (root / 'P1/bin/Release/net10.0/P0.dll').exists()
            assert run(DOTNET, output / 'P2.dll').stdout.strip() == str(value)
        build(1, 0)
        build(1, 3)
        (root / 'P0/Code.cs').write_text('public class P0 { public const int Value = 2; }')
        build(2, 0)
        build(2, 3)
        print('PASS: compile aliases, Private=false, reference constant invalidation and replay')


if __name__ == '__main__':
    main()
