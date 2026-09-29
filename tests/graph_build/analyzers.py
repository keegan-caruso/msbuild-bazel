"""Dependency-produced analyzer files must not be staged from old bin outputs."""

import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-analyzers-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'source'
        for name in ['Generator', 'App']:
            (root / name).mkdir(parents=True)
        project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>{}</PropertyGroup>{}</Project>'
        (root / 'Generator/Generator.csproj').write_text(project.format('', '<ItemGroup>' + ''.join(
            f'<Reference Include="{name}" HintPath="$(MSBuildBinPath)/Roslyn/bincore/{name}.dll" Private="false" />'
            for name in ['Microsoft.CodeAnalysis', 'Microsoft.CodeAnalysis.CSharp']) + '<None Include="$(OutputPath)$(AssemblyName).dll" Pack="true" /></ItemGroup>'))
        generator = root / 'Generator/Code.cs'
        def code(value):
            return 'using Microsoft.CodeAnalysis; [Generator] public class Generate : ISourceGenerator { public void Initialize(GeneratorInitializationContext context) {} public void Execute(GeneratorExecutionContext context) { context.AddSource("Value.g.cs", "public static class Value { public static int Number => ' + str(value) + '; }"); }}'
        generator.write_text(code(1))
        (root / 'App/App.csproj').write_text(project.format('<OutputType>Exe</OutputType>', '<ItemGroup>'
            '<ProjectReference Include="../Generator/Generator.csproj" ReferenceOutputAssembly="false" />'
            '<Analyzer Include="../Generator/bin/Release/net10.0/Generator.dll" /></ItemGroup>'))
        (root / 'App/Code.cs').write_text('System.Console.WriteLine(Value.Number);')
        sync = [DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root, SDK / 'sdk/10.0.400', 'App/App.csproj', '--graph']
        run(*sync)
        contract = root / 'graph.generated.json'
        assert not any('/bin/' in file for project in json.loads(contract.read_text())['Projects'].values() for config in project['Configurations'] for file in config['Inputs'])
        report = base / 'report.json'
        def build(value, hits):
            for name in ['Generator', 'App']:
                for folder in ['bin', 'obj']:
                    shutil.rmtree(root / name / folder, ignore_errors=True)
            run(DOTNET, RUNNER, 'action', root, contract, report, base / 'cache')
            assert json.loads(report.read_text())['hits'] == hits, report.read_text()
            assert run(DOTNET, root / 'App/bin/Release/net10.0/App.dll').stdout.strip() == str(value)
        build(1, 0)
        build(1, 2)
        # Sync must also exclude an already-built producer output.
        run(*sync, '--check')
        generator.write_text(code(2))
        build(2, 0)
        build(2, 2)
        authored = root / 'Generator/Generator.csproj'
        original = authored.read_text()
        (root / 'Generator/external.dll').write_bytes(b'undeclared assembly')
        authored.write_text(original.replace('$(MSBuildBinPath)/Roslyn/bincore/Microsoft.CodeAnalysis.dll', '$(MSBuildProjectDirectory)/external.dll'))
        assert 'SDK/package-owned assembly references' in run(*sync, success=False).stderr
        print('PASS: source-built analyzer scheduling, stale-bin exclusion, replay and body-edit invalidation')


if __name__ == '__main__':
    main()
