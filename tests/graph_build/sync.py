"""Generate graph contracts from SDK evaluation, then execute and replay them."""

import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, fixture, run

SYNC = ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll'


def main():
    with tempfile.TemporaryDirectory(prefix='graph-sync-') as temporary:
        directory = Path(temporary).resolve()
        root = directory / 'workspace'
        root.mkdir()
        fixture(root)
        command = [DOTNET, SYNC, root, SDK / 'sdk/10.0.400', 'P2/P2.csproj', '--graph']
        run(*command)
        run(*command, '--check')
        contract = root / 'graph.generated.json'
        generated = json.loads(contract.read_text())
        assert generated['Version'] == 2
        assert len(generated['Projects']) == 3
        assert str(root) not in contract.read_text()
        (root / 'P0/Extra.cs').write_text('public class Extra {}')
        assert 'stale' in run(*command, '--check', success=False).stderr
        run(*command)
        report = directory / 'report.json'
        cache = directory / 'cache'
        run(DOTNET, RUNNER, 'action', root, contract, report, cache)
        assert json.loads(report.read_text())['misses'] == 3
        for project in root.glob('P*'):
            shutil.rmtree(project / 'bin')
            shutil.rmtree(project / 'obj/Release')
        run(DOTNET, RUNNER, 'action', root, contract, report, cache)
        assert json.loads(report.read_text())['hits'] == 3
        assert run(DOTNET, root / 'P2/bin/Release/net10.0/P2.dll').stdout.strip() == '1'
        run(*command, '--check')
        # A new task must not silently receive a source-only contract.
        project = root / 'P0/P0.csproj'
        original = project.read_text()
        project.write_text(original.replace('</Project>', '<Target Name="Custom" BeforeTargets="Build" /></Project>'))
        assert 'custom targets/tasks' in run(*command, success=False).stderr
        project.write_text(original.replace('</Project>', '<ItemGroup><PackageReference Include="Unknown" Version="1.0.0" /></ItemGroup></Project>'))
        assert 'package-free' in run(*command, success=False).stderr
        project.write_text(original)
        contract.write_text('{}')
        assert 'Refusing to overwrite' in run(*command, success=False).stderr
        multi = directory / 'multi'
        multi.mkdir()
        (multi / 'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks></PropertyGroup></Project>')
        (multi / 'Code.cs').write_text('public class Library {}')
        run(DOTNET, SYNC, multi, SDK / 'sdk/10.0.400', 'Library.csproj', '--graph')
        staged = directory / 'multi-staged'
        staged.mkdir()
        for name in ['Library.csproj', 'Code.cs']:
            shutil.copyfile(multi / name, staged / name)
        run(DOTNET, RUNNER, 'action', staged, multi / 'graph.generated.json', report, directory / 'multi-cache')
        assert json.loads(report.read_text())['misses'] == 2
        print('PASS: generated graph build/replay, freshness, custom/package rejection, authored-file protection')


if __name__ == '__main__':
    main()
