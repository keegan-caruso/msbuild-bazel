"""Custom SDK compiler contracts stay separate from implementation artifacts."""

import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-compiler-reference-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        fixture(root)
        (root / 'Api').mkdir()
        (root / 'Api/Api.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><AssemblyName>P0</AssemblyName><ProduceOnlyReferenceAssembly>true</ProduceOnlyReferenceAssembly></PropertyGroup></Project>')
        api = root / 'Api/Code.cs'
        api.write_text('public class P0 { public static int Value() => throw null!; }')
        p0 = root / 'P0/P0.csproj'
        p0.write_text(p0.read_text().replace('</Project>', '<PropertyGroup><ProduceReferenceAssembly>false</ProduceReferenceAssembly></PropertyGroup><ItemGroup><ProjectReference Include="../Api/Api.csproj" ReferenceOutputAssembly="false" /></ItemGroup></Project>'))
        targets = root / 'Directory.Build.targets'
        targets.write_text('''<Project><Target Name="UseAuthoredApi" AfterTargets="FindReferenceAssembliesForReferences" Condition="'$(MSBuildProjectName)' == 'P1' or '$(MSBuildProjectName)' == 'P2'">
<ItemGroup><ReferencePathWithRefAssemblies Remove="$(MSBuildThisFileDirectory)P0/bin/$(Configuration)/$(TargetFramework)/P0.dll" />
<ReferencePathWithRefAssemblies Include="$(MSBuildThisFileDirectory)Api/bin/$(Configuration)/$(TargetFramework)/P0.dll" /></ItemGroup>
</Target></Project>''')
        mapping = {'projectDefaults': {'referenceBoundary': True, 'documents': {'Directory.Build.targets': {
            'sha256': hashlib.sha256(targets.read_bytes()).hexdigest(), 'targets': ['UseAuthoredApi'], 'tasks': [], 'inputs': []}}}}
        mapping_path = base / 'mapping.json'
        contract = root / 'graph.generated.json'
        report = base / 'report.json'
        def sync(success=True):
            mapping_path.write_text(json.dumps(mapping))
            return run(DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root,
                       SDK / 'sdk/10.0.400', 'P2/P2.csproj', '--mappings', mapping_path, success=success)
        def build(hits, value, cache):
            for name in ['P0', 'P1', 'P2', 'Api']:
                for folder in ['bin', 'obj']:
                    shutil.rmtree(root / name / folder, ignore_errors=True)
            run(DOTNET, RUNNER, 'action', root, contract, report, base / cache)
            assert json.loads(report.read_text())['hits'] == hits, report.read_text()
            assert run(DOTNET, root / 'P2/bin/Release/net10.0/P2.dll').stdout.strip() == str(value)
            return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                    for name in ['P0', 'P1', 'P2', 'Api'] for folder in ['bin', 'obj/Release']
                    for p in (root / name / folder).rglob('*') if p.is_file() and not p.name.endswith('.AssemblyReference.cache')}
        sync()
        build(0, 1, 'conservative')
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 2; }')
        # The ordinary fallback hashes the implementation because TargetRefPath is absent.
        build(1, 2, 'conservative')
        mapping['projects'] = {'P0/P0.csproj': {'referenceBoundary': True,
            'compilerReference': 'Api/bin/$(Configuration)/$(TargetFramework)/P0.dll',
            'documents': mapping['projectDefaults']['documents']}}
        sync()
        assert json.loads(contract.read_text())['Version'] == 7
        assert json.loads(contract.read_text())['Projects']['P0/P0.csproj']['Configurations'][0]['CompilerReference'] == 'Api/bin/Release/net10.0/P0.dll'
        build(0, 2, 'explicit')
        build(4, 2, 'explicit')
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 3; }')
        outputs = build(3, 3, 'explicit')
        assert outputs == build(0, 3, 'body-control')
        api.write_text('public class P0 { public static int Value() => throw null!; public static int Added() => throw null!; }')
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 3; public static int Added() => 4; }')
        assert build(0, 3, 'explicit') == build(0, 3, 'api-control')
        mapping['projects']['P1/P1.csproj'] = {'referenceBoundary': True,
            'implementationDependencies': ['P0/P0.csproj'], 'documents': mapping['projectDefaults']['documents']}
        sync()
        build(0, 3, 'implementation')
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => 4; public static int Added() => 4; }')
        assert build(2, 4, 'implementation') == build(0, 4, 'implementation-control')
        # A stale schema must fail before publishing a report.
        current = contract.read_text()
        old = json.loads(current)
        old['Version'] = 6
        contract.write_text(json.dumps(old))
        report.unlink()
        assert 'require graph contract version 7' in run(DOTNET, RUNNER, 'action', root, contract, report, base / 'legacy', success=False).stderr
        assert not report.exists()
        contract.write_text(current)
        missing = json.loads(current)
        missing['Projects']['P0/P0.csproj']['Configurations'][0]['CompilerReference'] = 'Api/bin/Release/net10.0/absent.dll'
        missing['Projects']['Api/Api.csproj']['Configurations'][0]['OutputFiles'].append('Api/bin/Release/net10.0/absent.dll')
        contract.write_text(json.dumps(missing))
        for name in ['P0', 'P1', 'P2', 'Api']:
            for folder in ['bin', 'obj']:
                shutil.rmtree(root / name / folder, ignore_errors=True)
        failed = run(DOTNET, RUNNER, 'action', root, contract, report, base / 'missing-artifact', success=False)
        assert 'Missing declared compiler reference' in failed.stdout + failed.stderr, failed.stdout + failed.stderr
        assert not report.exists()
        contract.write_text(current)
        for path, message in [('Api/bin/Release/net10.0/P0.pdb', 'configured managed DLL'),
                              ('P2/bin/Release/net10.0/P2.dll', 'producer dependency closure'),
                              ('Api/bin/Release/net10.0/missing.dll', 'producer dependency closure'),
                              ('../outside.dll', 'path'), ('/tmp/outside.dll', 'path')]:
            mapping['projects']['P0/P0.csproj']['compilerReference'] = path
            assert message.lower() in sync(False).stderr.lower()
            assert contract.read_text() == current
        mapping['projects']['P0/P0.csproj']['compilerReference'] = 'Api/bin/$(Configuration)/$(TargetFramework)/P0.dll'
        # Version 7 retains earlier directory, temporary-output and root-property contracts.
        (root / 'present').mkdir()
        mapping['projectDefaults']['inputDirectories'] = ['present']
        mapping['projectDefaults']['temporaryDirectories'] = ['$(IntermediateOutputPath)scratch']
        mapping['entryProperties'] = {'P2/P2.csproj': {'FixtureDimension': 'fixed'}}
        sync()
        data = json.loads(contract.read_text())
        assert data['Version'] == 7 and data['InputDirectories'] == ['present'] and data['TemporaryDirectories'] and data['EntryProperties']
        build(0, 4, 'composition')
        build(4, 4, 'composition')
        print('PASS: declared compiler artifacts preserve replay/body/API parity, implementation roles, output ownership, schema guards and contract composition')


if __name__ == '__main__':
    main()
