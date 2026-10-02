"""Qualify the isolated metadata measurement on real evaluated duplicate references."""

import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-reference-work-') as temporary:
        base = Path(temporary).resolve()
        driver = base / 'driver'
        driver.mkdir()
        upstream = ROOT / 'tests/graph_build/upstream'
        shutil.copyfile(upstream / 'RuntimeRawGraph.cs.txt', driver / 'Program.cs')
        shutil.copyfile(upstream / 'RuntimeRawGraph.csproj.txt', driver / 'Raw.csproj')
        run(DOTNET, 'build', driver / 'Raw.csproj', '-c', 'Release', '-p:UseSharedCompilation=false', '-p:NuGetAudit=false')
        root = base / 'workspace'
        root.mkdir()
        contract = fixture(root)
        contract['Properties']['DisableTransitiveProjectReferences'] = 'true'
        for project in contract['Projects'].values():
            project['ReferenceBoundary'] = True
        manifest = root / 'contract.json'
        manifest.write_text(json.dumps(contract))
        project = root / 'P1/P1.csproj'
        original = project.read_text()
        for name, metadata in [('ordinary', ''), ('implementation', 'ReferenceOutputAssembly="false"'),
                               ('item', 'OutputItemType="Probe"'), ('targets', 'Targets="Build"')]:
            project.write_text(original.replace('</Project>', '<ItemGroup><ProjectReference Include="../P0/./P0.csproj" '
                                                + metadata + ' /></ItemGroup></Project>'))
            report = base / (name + '.json')
            run(DOTNET, driver / 'bin/Release/net10.0/Raw.dll', root, manifest, 'reference-work', report)
            result = json.loads(report.read_text())
            assert result['rolesEqual'] and result['duplicateAuthoredPaths'] == 1 and result['compiledNodes'] == 3, result
            assert result['implementationReferences'] == int(name != 'ordinary'), result
        print('PASS: ordinary/implementation/item/target duplicate-path roles in the isolated measurement')


if __name__ == '__main__':
    main()
