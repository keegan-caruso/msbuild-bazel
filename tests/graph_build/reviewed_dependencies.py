"""Reviewed package/custom graphs distinguish compiler references from tools."""

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from qualify import DOTNET, ROOT, RUNNER, SDK, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='reviewed-graph-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        fixture(root)
        # A declared package runs a build target; it does not inspect dependency IL.
        package = base / 'packages/fixture.build/1.0.0'
        package.mkdir(parents=True)
        archive = package / 'fixture.build.1.0.0.nupkg'
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('Fixture.Build.nuspec', '<package><metadata><id>Fixture.Build</id><version>1.0.0</version><authors>fixture</authors><description>fixture</description></metadata></package>')
            output.writestr('buildTransitive/Fixture.Build.targets', '<Project><Target Name="PackageMarker" BeforeTargets="CoreCompile"><WriteLinesToFile File="$(IntermediateOutputPath)package-marker.txt" Lines="qualified" Overwrite="true" /></Target></Project>')
        with zipfile.ZipFile(archive) as package_zip:
            package_zip.extractall(package)
        manifest = base / 'inputs.json'
        manifest.write_text(json.dumps({'Inputs': [], 'PackageLock': ':packages', 'Packages': [
            {'Id': 'Fixture.Build', 'Version': '1.0.0', 'Runfile': 'fixture.build/1.0.0'}]}))
        (root / '.package-source').mkdir()
        shutil.copy(archive, root / '.package-source' / archive.name)
        p1 = root / 'P1/P1.csproj'
        p1.write_text(p1.read_text().replace('</Project>', '<ItemGroup><PackageReference Include="Fixture.Build" Version="1.0.0" /><ProjectReference Include="../Generator/Generator.csproj" OutputItemType="Analyzer" ReferenceOutputAssembly="false" /></ItemGroup></Project>'))
        (root / 'Generator').mkdir()
        (root / 'Generator/Generator.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup><ItemGroup>' + ''.join(
            f'<Reference Include="{name}" HintPath="$(MSBuildBinPath)/Roslyn/bincore/{name}.dll" Private="false" />' for name in ['Microsoft.CodeAnalysis', 'Microsoft.CodeAnalysis.CSharp']) + '</ItemGroup></Project>')
        def generator(value):
            (root / 'Generator/Code.cs').write_text('using Microsoft.CodeAnalysis; [Generator] public class G : ISourceGenerator { public void Initialize(GeneratorInitializationContext c) {} public void Execute(GeneratorExecutionContext c) { c.AddSource("Generated.cs", "internal static class Generated { internal static int Value => ' + str(value) + '; }"); }}')
        generator(10)
        (root / 'P1/Code.cs').write_text('public class P1 { public static int Value() => P0.Value() + Generated.Value; }')
        targets = root / 'Directory.Build.targets'
        targets.write_text('<Project><Target Name="ReviewedTarget" BeforeTargets="CoreCompile"><WriteLinesToFile File="$(IntermediateOutputPath)reviewed.txt" Lines="@(ProjectReference)" Overwrite="true" /></Target></Project>')
        mapping = {'projectDefaults': {'documents': {'Directory.Build.targets': {
            'sha256': hashlib.sha256(targets.read_bytes()).hexdigest(), 'targets': ['ReviewedTarget'], 'tasks': [], 'inputs': []}}}}
        mapping_path = base / 'mapping.json'
        contract = root / 'graph.generated.json'
        report = base / 'report.json'
        def sync(success=True):
            mapping_path.write_text(json.dumps(mapping))
            return run(DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root, SDK / 'sdk/10.0.400',
                       'P2/P2.csproj', '--graph', '--package-build', '--inputs', manifest, '--runfiles', base / 'packages', '--mappings', mapping_path, success=success)
        sync()
        assert not json.loads(contract.read_text())['Projects']['P2/P2.csproj']['Configurations'][0]['ReferenceBoundary']
        mapping['projectDefaults']['referenceBoundary'] = True
        sync()
        assert json.loads(contract.read_text())['Version'] == 3
        assert all(c['ReferenceBoundary'] for p in json.loads(contract.read_text())['Projects'].values() for c in p['Configurations'])
        def build(hits, value, cache='cache'):
            for name in ['P0', 'P1', 'P2', 'Generator']:
                for folder in ['bin', 'obj']:
                    shutil.rmtree(root / name / folder, ignore_errors=True)
            run(DOTNET, RUNNER, 'action', root, contract, report, base / cache)
            assert json.loads(report.read_text())['hits'] == hits, report.read_text()
            assert run(DOTNET, root / 'P2/bin/Release/net10.0/P2.dll').stdout.strip() == str(value)
            return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for name in ['P0', 'P1', 'P2', 'Generator'] for folder in ['bin', 'obj/Release']
                    for p in (root / name / folder).rglob('*') if p.is_file() and not p.name.endswith('.AssemblyReference.cache')}
        build(0, 11)
        build(4, 11)
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; }')
        outputs = build(3, 12)
        assert outputs == build(0, 12, 'body-control')
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; public static int Added() => 3; }')
        outputs = build(1, 12)
        assert outputs == build(0, 12, 'api-control')
        generator(20)
        outputs = build(2, 22)
        assert outputs == build(0, 22, 'generator-control')
        # A reviewed custom task can explicitly require a normal reference's implementation.
        mapping['projects'] = {'P1/P1.csproj': {'implementationDependencies': ['P0/P0.csproj']}}
        sync()
        current_contract = contract.read_text()
        legacy = json.loads(current_contract)
        legacy['Version'] = 2
        contract.write_text(json.dumps(legacy))
        failure = run(DOTNET, RUNNER, 'action', root, contract, report, base / 'legacy-cache', success=False).stderr
        assert 'require graph contract version 3' in failure, failure
        contract.write_text(current_contract)
        build(2, 22)
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 3; public static int Added() => 3; }')
        outputs = build(2, 23)
        assert outputs == build(0, 23, 'implementation-control')
        # Conventional XML beside a dependency DLL also supports reviewed boundaries.
        p0 = root / 'P0/P0.csproj'
        before_documentation = p0.read_text()
        p0.write_text(before_documentation.replace('</Project>', '<PropertyGroup><GenerateDocumentationFile>true</GenerateDocumentationFile><DocumentationFile>bin/$(Configuration)/$(TargetFramework)/P0.xml</DocumentationFile><NoWarn>$(NoWarn);1591</NoWarn></PropertyGroup></Project>'))
        mapping['projects'] = {}
        sync()
        build(0, 23, 'documentation-cache')
        build(4, 23, 'documentation-cache')
        documentation = root / 'P2/bin/Release/net10.0/P0.xml'
        assert documentation.read_bytes() == (root / 'P0/bin/Release/net10.0/P0.xml').read_bytes()
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 4; public static int Added() => 3; }')
        outputs = build(3, 24, 'documentation-cache')
        assert outputs == build(0, 24, 'documentation-body-control')
        # A custom documentation filename is still outside the standard copy contract.
        p0.write_text(p0.read_text().replace('bin/$(Configuration)/$(TargetFramework)/P0.xml', 'bin/$(Configuration)/$(TargetFramework)/custom.xml'))
        assert 'standard managed outputs' in sync(False).stderr
        p0.write_text(before_documentation)
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 3; public static int Added() => 3; }')
        # Content propagates even with transitive compiler references disabled.
        mapping['projects'] = {}
        mapping['projectDefaults']['properties'] = {'DisableTransitiveProjectReferences': 'true'}
        p0 = root / 'P0/P0.csproj'
        p0.write_text(p0.read_text().replace('</Project>', '<ItemGroup><Content Include="data.txt" CopyToOutputDirectory="PreserveNewest" /><AdditionalFiles Include="Code.cs" /></ItemGroup></Project>'))
        data = root / 'P0/data.txt'
        data.write_text('first')
        sync()
        build(0, 23)
        data.write_text('second')
        outputs = build(1, 23)
        assert (root / 'P2/bin/Release/net10.0/data.txt').read_text() == 'second'
        assert outputs == build(0, 23, 'content-control')
        # A file consumed both as Compile and AdditionalFiles is not compiler-only.
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 4; public static int Added() => 3; }')
        outputs = build(1, 24)
        assert outputs == build(0, 24, 'additional-control')
        mapping['projects'] = {'P1/P1.csproj': {'implementationDependencies': ['P2/P2.csproj']}}

        assert 'direct ProjectReference' in sync(False).stderr
        print('PASS: reviewed package/target boundaries, runtime copies, API changes, analyzer bodies, explicit implementation edges, propagated content, dual-role sources and controls')


def multitarget():
    with tempfile.TemporaryDirectory(prefix='reviewed-multitarget-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        fixture(root)
        for path in root.glob('P*/*.csproj'):
            path.write_text(path.read_text().replace('<TargetFramework>net10.0</TargetFramework>',
                '<TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks>'))
        mapping = base / 'mapping.json'
        mapping.write_text(json.dumps({'projectDefaults': {'referenceBoundary': True}}))
        command = [DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root,
                   SDK / 'sdk/10.0.400', 'P2/P2.csproj', '--graph', '--mappings', mapping]
        # Different framework producers cannot silently own the same runtime copy.
        assert 'Ambiguous graph dependency copy' in run(*command, success=False).stderr
        for path in root.glob('P*/*.csproj'):
            path.write_text(path.read_text().replace('net10.0;net10.0-windows', 'net10.0'))
        run(*command)
        contract = root / 'graph.generated.json'
        report = base / 'report.json'
        def build(hits, value):
            for project in root.glob('P*'):
                for tree in ['bin', 'obj']:
                    shutil.rmtree(project / tree, ignore_errors=True)
            run(DOTNET, RUNNER, 'action', root, contract, report, base / 'cache')
            assert json.loads(report.read_text())['hits'] == hits, report.read_text()
            for framework in ['net10.0']:
                assert run(DOTNET, root / f'P2/bin/Release/{framework}/P2.dll').stdout.strip() == str(value)
        build(0, 1)
        build(3, 1)
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; }')
        build(2, 2)
        print('PASS: reviewed outer-node coordination, replay, body edit and ambiguous-copy rejection')


if __name__ == '__main__':
    main()
    multitarget()
