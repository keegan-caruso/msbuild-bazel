"""Explicit compiler selection does not prune SDK coordination builds."""

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-consumer-reference-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        fixture(root)
        (root / 'Api').mkdir()
        (root / 'Api/Api.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks><AssemblyName>P0</AssemblyName><ProduceOnlyReferenceAssembly>true</ProduceOnlyReferenceAssembly></PropertyGroup></Project>')
        api = root / 'Api/Code.cs'
        api.write_text('public class P0 { public static int Value() => throw null!; }')
        p0 = root / 'P0/P0.csproj'
        p0.write_text(p0.read_text().replace('<TargetFramework>net10.0</TargetFramework>', '<TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks>').replace('</Project>', '<PropertyGroup><ProduceReferenceAssembly>false</ProduceReferenceAssembly></PropertyGroup><ItemGroup><ProjectReference Include="../Api/Api.csproj" ReferenceOutputAssembly="false" /></ItemGroup></Project>'))
        p1 = root / 'P1/P1.csproj'
        p1.write_text(p1.read_text().replace('Include="../P0/P0.csproj"', 'Include="../P0/P0.csproj" Private="false"'))
        targets = root / 'Directory.Build.targets'
        targets.write_text('''<Project><Target Name="UseAuthoredApi" AfterTargets="FindReferenceAssembliesForReferences" Condition="'$(MSBuildProjectName)' == 'P1' or '$(MSBuildProjectName)' == 'P2'">
<ItemGroup><ReferencePathWithRefAssemblies Remove="$(MSBuildThisFileDirectory)P0/bin/$(Configuration)/net10.0/P0.dll" />
<ReferencePathWithRefAssemblies Include="$(MSBuildThisFileDirectory)Api/bin/$(Configuration)/net10.0/P0.dll" /></ItemGroup>
</Target></Project>''')
        document = {'Directory.Build.targets': {'sha256': hashlib.sha256(targets.read_bytes()).hexdigest(), 'targets': ['UseAuthoredApi'], 'tasks': [], 'inputs': []}}
        mapping = {'projectDefaults': {'referenceBoundary': True, 'documents': document}, 'projects': {}}
        contract = root / 'graph.generated.json'
        report = base / 'report.json'
        mapping_path = base / 'mapping.json'

        def sync(success=True):
            mapping_path.write_text(json.dumps(mapping))
            return run(DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root,
                       SDK / 'sdk/10.0.400', 'P0/P0.csproj', 'P2/P2.csproj', '--mappings', mapping_path, success=success)

        def build(hits, value, cache):
            for name in ['P0', 'P1', 'P2', 'Api']:
                for folder in ['bin', 'obj']:
                    shutil.rmtree(root / name / folder, ignore_errors=True)
            run(DOTNET, RUNNER, 'action', root, contract, report, base / cache)
            data = json.loads(report.read_text())
            assert (data['hits'], data['misses']) == (hits, 6 - hits), data
            # Compiler selection is independent of runtime composition. The
            # non-copying producer is supplied explicitly to this execution control.
            execution = base / 'execution'
            shutil.rmtree(execution, ignore_errors=True)
            shutil.copytree(root / 'P2/bin/Release/net10.0', execution)
            shutil.copyfile(root / 'P0/bin/Release/net10.0/P0.dll', execution / 'P0.dll')
            (execution / 'P2.deps.json').unlink()
            assert run(DOTNET, execution / 'P2.dll').stdout.strip() == str(value)
            return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for name in ['P0', 'P1', 'P2', 'Api'] for folder in ['bin', 'obj/Release']
                    for p in (root / name / folder).rglob('*') if p.is_file() and not p.name.endswith('.AssemblyReference.cache')}

        def equal(actual, expected):
            differences = {p: [actual.get(p), expected.get(p)] for p in actual.keys() | expected.keys() if actual.get(p) != expected.get(p)}
            assert not differences, differences

        sync()
        # SDK transitive CopyLocal can differ from a grandchild's Private=false.
        # An undeclared implementation copy must fail before saving a snapshot.
        failed = run(DOTNET, RUNNER, 'action', root, contract, report, base / 'unmapped-copy', success=False)
        assert 'Undeclared dependency copy' in failed.stdout + failed.stderr, failed.stdout + failed.stderr
        assert not report.exists()
        p2 = root / 'P2/P2.csproj'
        p2.write_text(p2.read_text().replace('</Project>', '<ItemGroup><ProjectReference Include="../P0/P0.csproj" Private="false" /></ItemGroup></Project>'))
        sync()
        build(0, 1, 'conservative')
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; }')
        build(2, 2, 'conservative')
        references = {'P0/P0.csproj': 'Api/bin/$(Configuration)/net10.0/P0.dll',
                      'Api/Api.csproj': 'Api/bin/$(Configuration)/net10.0/P0.dll'}
        for consumer in ['P1', 'P2']:
            mapping['projects'][f'{consumer}/{consumer}.csproj'] = {'referenceBoundary': True, 'documents': document, 'compilerReferences': references}
        sync()
        assert json.loads(contract.read_text())['Version'] == 8
        build(0, 2, 'selected')
        build(6, 2, 'selected')
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 3; }')
        equal(build(4, 3, 'selected'), build(0, 3, 'body-control'))
        # The unused API configuration still builds, without recompiling net10 consumers.
        api.write_text('public class P0 { public static int Value() => throw null!;\n#if WINDOWS\npublic static int Unused() => throw null!;\n#endif\n}')
        equal(build(2, 3, 'selected'), build(0, 3, 'unused-api-control'))
        api.write_text(api.read_text().replace('public class P0 {', 'public class P0 { public static int Added() => throw null!;'))
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 3; public static int Added() => 4; }')
        equal(build(0, 3, 'selected'), build(0, 3, 'api-control'))
        mapping['projects']['P1/P1.csproj']['implementationDependencies'] = ['P0/P0.csproj']
        sync()
        build(0, 3, 'implementation')
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 4; public static int Added() => 4; }')
        equal(build(3, 4, 'implementation'), build(0, 4, 'implementation-control'))
        current = contract.read_text()
        invalid = json.loads(current)
        invalid['Version'] = 7
        contract.write_text(json.dumps(invalid))
        report.unlink()
        assert 'require graph contract version 8' in run(DOTNET, RUNNER, 'inspect', root, contract, report, success=False).stderr
        assert not report.exists()
        contract.write_text(current)
        for producer, artifact, message in [('P2/P2.csproj', 'P2/bin/Release/net10.0/P2.dll', 'producer dependency closure'),
                                            ('P0/P0.csproj', 'P2/bin/Release/net10.0/P2.dll', 'producer dependency closure'),
                                            ('P0/P0.csproj', 'Api/bin/Release/net10.0/P0.pdb', 'managed DLL consumer'),
                                            ('../P0.csproj', 'Api/bin/Release/net10.0/P0.dll', 'path')]:
            mapping['projects']['P1/P1.csproj']['compilerReferences'] = {producer: artifact}
            assert message.lower() in sync(False).stderr.lower()
            assert contract.read_text() == current
        mapping['projects']['P1/P1.csproj']['compilerReferences'] = references
        mapping['projects']['P1/P1.csproj']['referenceBoundary'] = False
        assert 'reviewed reference boundary' in sync(False).stderr
        assert contract.read_text() == current
        mapping['projects']['P1/P1.csproj']['referenceBoundary'] = True
        (root / 'present').mkdir()
        mapping['projectDefaults']['inputDirectories'] = ['present']
        mapping['projectDefaults']['temporaryDirectories'] = ['$(IntermediateOutputPath)scratch']
        mapping['entryProperties'] = {'P2/P2.csproj': {'Configuration': 'Release'}}
        sync()
        composed = json.loads(contract.read_text())
        assert composed['Version'] == 8 and composed['InputDirectories'] and composed['TemporaryDirectories'] and composed['EntryProperties']
        build(0, 4, 'composition')
        build(6, 4, 'composition')
        print('PASS: all configured builds retained, selected body/API and unused-framework edits, implementation roles, exact fresh parity and fail-closed consumer contracts')


if __name__ == '__main__':
    main()
