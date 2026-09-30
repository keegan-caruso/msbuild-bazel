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
        # Project's default IDE evaluation expands inactive item expressions.
        # Command-line build semantics skip them, including disabled platform globs.
        props = root / 'Directory.Build.props'
        props.write_text('''<Project><ItemGroup Condition="false"><Compile Include="$([System.Int32]::Parse('inactive-item-must-not-expand'))" /></ItemGroup></Project>''')
        command = [DOTNET, SYNC, root, SDK / 'sdk/10.0.400', 'P2/P2.csproj', '--graph']
        run(*command)
        run(*command, '--check')
        inactive = props.read_text()
        props.write_text(inactive.replace('Condition="false"', 'Condition="true"'))
        assert 'inactive-item-must-not-expand' in run(*command, success=False).stderr
        props.write_text(inactive)
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
        # A stale definition must fail before Restore can run a newly added task.
        entry = root / 'P2/P2.csproj'
        original_entry = entry.read_text()
        entry.write_text(original_entry.replace('</Project>', '<Target Name="RestoreMarker" BeforeTargets="Restore">'
            '<WriteLinesToFile File="$(MSBuildProjectDirectory)/restore-ran.txt" Lines="ran" /></Target></Project>'))
        failure = run(DOTNET, RUNNER, 'action', root, contract, report, cache, success=False)
        assert 'Graph definition changed' in failure.stderr
        assert not (root / 'P2/restore-ran.txt').exists()
        entry.write_text(original_entry)
        # A new task must not silently receive a source-only contract.
        project = root / 'P0/P0.csproj'
        original = project.read_text()
        project.write_text(original.replace('</Project>', '<Target Name="Custom" BeforeTargets="Build" /></Project>'))
        assert 'custom targets/tasks' in run(*command, success=False).stderr
        project.write_text(original.replace('</Project>', '<ItemGroup><PackageReference Include="Unknown" Version="1.0.0" /></ItemGroup></Project>'))
        assert 'msbuild_sync.package_lock' in run(*command, success=False).stderr
        project.write_text(original)
        contract.write_text('{}')
        assert 'Refusing to overwrite' in run(*command, success=False).stderr
        multi = directory / 'multi'
        multi.mkdir()
        (multi / 'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks>'
            '<EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup></Project>')
        (multi / 'Code.cs').write_text('public class Library {}')
        # Outer SDK evaluation has no language extension or compiler target.
        # Imported Compile placeholders must be checked by the inner builds.
        (multi / 'Directory.Build.targets').write_text('<Project><ItemGroup>'
            '<Compile Include="Code.cs" /><Compile Include="Helper$(DefaultLanguageSourceExtension)" />'
            '<Compile Include="Outer.cs" Condition="&apos;$(IsCrossTargetingBuild)&apos; == &apos;true&apos;" />'
            '<None Include="$(IntermediateOutputPath)outer-placeholder.txt" Condition="&apos;$(IsCrossTargetingBuild)&apos; == &apos;true&apos;" />'
            '</ItemGroup></Project>')
        (multi / 'Helper.cs').write_text('public class Helper {}')
        (multi / 'Outer.cs').write_text('// Existing outer evaluation input must remain declared.')
        run(DOTNET, SYNC, multi, SDK / 'sdk/10.0.400', 'Library.csproj', '--graph')
        staged = directory / 'multi-staged'
        staged.mkdir()
        for name in ['Library.csproj', 'Code.cs', 'Helper.cs', 'Outer.cs', 'Directory.Build.targets']:
            shutil.copyfile(multi / name, staged / name)
        run(DOTNET, RUNNER, 'action', staged, multi / 'graph.generated.json', report, directory / 'multi-cache')
        assert json.loads(report.read_text())['misses'] == 2
        (multi / 'Helper.cs').unlink()
        missing = run(DOTNET, SYNC, multi, SDK / 'sdk/10.0.400', 'Library.csproj', '--graph', success=False)
        assert 'Helper.cs' in missing.stderr and 'no project producer' in missing.stderr
        mixed = directory / 'mixed'
        for name in ['App', 'Library']:
            (mixed / name).mkdir(parents=True)
        (mixed / 'Library/Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
        (mixed / 'Library/Code.cs').write_text('public class Library { public static int Value => 42; }')
        (mixed / 'App/App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0-windows</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Library/Library.csproj" /></ItemGroup></Project>')
        (mixed / 'App/Code.cs').write_text('System.Console.WriteLine(Library.Value);')
        run(DOTNET, SYNC, mixed, SDK / 'sdk/10.0.400', 'App/App.csproj', '--graph', '--framework', 'net10.0-windows')
        run(DOTNET, RUNNER, 'action', mixed, mixed / 'graph.generated.json', report, directory / 'mixed-cache')
        assert run(DOTNET, mixed / 'App/bin/Release/net10.0-windows/App.dll').stdout.strip() == '42'
        assert (mixed / 'Library/bin/Release/net10.0/Library.dll').is_file()
        print('PASS: generated graph build/replay, freshness, custom/package rejection, authored-file protection')


if __name__ == '__main__':
    main()
