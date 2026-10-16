"""Qualify inner-only linker output ownership on a tiny SDK multi-target graph."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from runtime_contract import bind_outer_outputs

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sdk', type=Path, help='declared SDK extraction containing dotnet and sdk/10.0.400')
    args = parser.parse_args()
    sdk = args.sdk.resolve()
    tool = ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll'
    assert tool.is_file(), 'Build ProjectSync first'
    with tempfile.TemporaryDirectory(prefix='runtime-outer-outputs-') as temporary:
        root = Path(temporary)
        project = root / 'Library.csproj'
        project.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks></PropertyGroup><ItemGroup><Compile Remove="Generator/**/*.cs" /><ProjectReference Include="Generator/Generator.csproj" ReferenceOutputAssembly="false" OutputItemType="Analyzer" /></ItemGroup></Project>')
        (root / 'Code.cs').write_text('public class Library { public static int Value() => Generated.Value; }')
        generator = root / 'Generator'
        generator.mkdir()
        references = ''.join('<Reference Include="' + name + '" HintPath="$(MSBuildBinPath)/Roslyn/bincore/' + name + '.dll" Private="false" />' for name in ['Microsoft.CodeAnalysis', 'Microsoft.CodeAnalysis.CSharp'])
        (generator / 'Generator.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup>' + references + '</ItemGroup></Project>')
        (generator / 'Code.cs').write_text('using Microsoft.CodeAnalysis; [Generator] public class Generate : ISourceGenerator { public void Initialize(GeneratorInitializationContext context) {} public void Execute(GeneratorExecutionContext context) { context.AddSource("Value.g.cs", "public static class Generated { public const int Value = 1; }"); } }')
        target = root / 'Directory.Build.targets'
        target.write_text('''<Project>
<ItemGroup Condition="'$(MSBuildProjectName)' == 'Library'"><ILLinkSubstitutionsXmls Include="$(IntermediateOutputPath)ILLink.Resources.Substitutions.xml" /></ItemGroup>
<Target Name="GenerateLinkerOutput" BeforeTargets="CoreCompile" Condition="'$(TargetFramework)' != '' and '$(MSBuildProjectName)' == 'Library'">
<WriteLinesToFile File="@(ILLinkSubstitutionsXmls)" Lines="generated" Overwrite="true" />
</Target></Project>''')
        mapping = dict(projectDefaults=dict(outputFiles=["@(ILLinkSubstitutionsXmls->WithMetadataValue('Filename', 'ILLink.Resources.Substitutions'))"],
            evaluationItems=['ILLinkSubstitutionsXmls'], documents={'Directory.Build.targets': dict(
                sha256=hashlib.sha256(target.read_bytes()).hexdigest(), targets=['GenerateLinkerOutput'], tasks=[], inputs=[])}))
        mapping_path = root / 'mappings.json'
        command = [str(sdk / 'dotnet'), str(tool), str(root), str(sdk / 'sdk/10.0.400'), 'Library.csproj', '--mappings', str(mapping_path)]
        mapping_path.write_text(json.dumps(mapping))
        subprocess.run(command, check=True)
        contract = root / 'graph.generated.json'
        variants = json.loads(contract.read_text())['Projects']['Library.csproj']['Configurations']
        outer = next(row for row in variants if not row['Properties']['TargetFramework'])
        assert not outer['OutputDirectories'] and outer['OutputFiles'] == ['obj/Release/ILLink.Resources.Substitutions.xml']
        original = copy.deepcopy(mapping)
        bind_outer_outputs(mapping)
        assert original['projectDefaults']['outputFiles'] == mapping['projectDefaults']['outputFiles']
        mapping_path.write_text(json.dumps(mapping))
        subprocess.run(command, check=True)
        subprocess.run(command + ['--check'], check=True)
        variants = json.loads(contract.read_text())['Projects']['Library.csproj']['Configurations']
        outer = next(row for row in variants if not row['Properties']['TargetFramework'])
        assert outer['OutputFiles'] == outer['OutputDirectories'] == []
        assert outer['ImplementationDependencies'] == [], outer
        assert all(row['ImplementationDependencies'] == ['Generator/Generator.csproj'] for row in variants if row['Properties']['TargetFramework']), variants
        inner = [row for row in variants if row['Properties']['TargetFramework']]
        assert len(inner) == 2 and all(len(row['OutputFiles']) == 1 for row in inner)
        subprocess.run([str(sdk / 'dotnet'), 'msbuild', str(project), '-restore', '-t:Build', '-p:Configuration=Release', '-p:NuGetAudit=false', '-v:q', '-nologo'], check=True)
        assert all((root / row['OutputFiles'][0]).read_text().strip() == 'generated' for row in inner)
        assert not (root / 'obj/Release/ILLink.Resources.Substitutions.xml').exists()
        assert sum(bool(row['OutputDirectories'] or row['OutputFiles']) for row in variants) == 2
    print('PASS: SDK emits linker files only for inner frameworks; outer coordination owns no phantom output')


if __name__ == '__main__':
    main()
