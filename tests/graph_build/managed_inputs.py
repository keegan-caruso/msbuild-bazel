"""Each declared managed input invalidates its owners and refreshes runtime copies."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-managed-inputs-') as temporary:
        base = Path(temporary).resolve()
        root, raw = base / 'workspace', base / 'raw'
        root.mkdir()
        (root / 'Shared').mkdir()
        (root / 'Directory.Build.props').write_text('<Project><PropertyGroup><DisableTransitiveProjectReferences>true</DisableTransitiveProjectReferences></PropertyGroup></Project>')
        (root / 'NuGet.Config').write_text('<configuration><packageSources><clear/></packageSources><fallbackPackageFolders><clear/></fallbackPackageFolders></configuration>')
        (root / 'Shared/Code.cs').write_text('internal static class Shared { internal static string Value => "shared-one"; }')
        for name in ['P0', 'P1', 'App', 'Unrelated']:
            folder = root / name
            folder.mkdir()
            extra = '<OutputType>Exe</OutputType>' if name == 'App' else ''
            items = '<ItemGroup><ProjectReference Include="../P0/P0.csproj"/><ProjectReference Include="../P1/P1.csproj"/></ItemGroup>' if name == 'App' else ''
            if name in ['P0', 'P1']:
                items += '<ItemGroup><Compile Include="../Shared/Code.cs"/></ItemGroup>'
            if name == 'P0':
                items += '<Import Project="Options.props"/><Import Project="Generate.targets"/>'
            (folder / (name + '.csproj')).write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>' + extra + '</PropertyGroup>' + items + '</Project>')
            code = {'P0': 'public static class P0 { public static string Value() => Shared.Value + "/" + new System.Resources.ResourceManager("P0.Resource",typeof(P0).Assembly).GetString("Value") + "/" + Generated.Value; }',
                    'P1': 'public static class P1 { public static string Value() => Shared.Value; }',
                    'App': 'System.Console.WriteLine(P0.Value() + ";" + P1.Value());',
                    'Unrelated': 'public class Unrelated { }'}[name]
            (folder / 'Code.cs').write_text(code)
        (root / 'P0/Resource.resx').write_text('<root><resheader name="resmimetype"><value>text/microsoft-resx</value></resheader><resheader name="version"><value>2.0</value></resheader><data name="Value" xml:space="preserve"><value>resource-one</value></data></root>')
        (root / 'P0/meta.txt').write_text('metadata-one')
        (root / 'P0/Options.props').write_text('<Project><PropertyGroup><QualificationValue>property-one</QualificationValue></PropertyGroup></Project>')
        target = '<Project><Target Name="Generate" BeforeTargets="CoreCompile"><WriteLinesToFile File="$(IntermediateOutputPath)Generated.cs" Lines="internal static class Generated { internal static string Value =&gt; &quot;$([System.IO.File]::ReadAllText(\'$(MSBuildProjectDirectory)/meta.txt\'))/$(QualificationValue)&quot;%3B }" Overwrite="true" WriteOnlyWhenDifferent="true"/><ItemGroup><Compile Include="$(IntermediateOutputPath)Generated.cs"/></ItemGroup></Target></Project>'
        (root / 'P0/Generate.targets').write_text(target)
        mapping = base / 'mapping.json'
        mapping.write_text(json.dumps({'projectDefaults': {'referenceBoundary': True, 'documents': {
            'P0/Generate.targets': {'sha256': hashlib.sha256(target.encode()).hexdigest(), 'targets': ['Generate'], 'tasks': [], 'inputs': ['P0/meta.txt']}}}}))
        sync = ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll'
        run(DOTNET, sync, root, SDK / 'sdk/10.0.400', 'App/App.csproj', 'Unrelated/Unrelated.csproj', '--mappings', mapping)
        manifest = root / 'graph.generated.json'
        contract = json.loads(manifest.read_text())
        shutil.copytree(root, raw)
        for entry in ['App/App.csproj', 'Unrelated/Unrelated.csproj']:
            run(DOTNET, 'restore', raw / entry, '--configfile', raw / 'NuGet.Config', '-p:NuGetAudit=false')
        driver = base / 'driver'
        driver.mkdir()
        fixtures = ROOT / 'tests/graph_build/upstream'
        shutil.copyfile(fixtures / 'RuntimeRawGraph.cs.txt', driver / 'Program.cs')
        shutil.copyfile(fixtures / 'RuntimeRawGraph.csproj.txt', driver / 'Raw.csproj')
        run(DOTNET, 'build', driver / 'Raw.csproj', '-c', 'Release', '-p:UseSharedCompilation=false')
        reader = base / 'reader'
        reader.mkdir()
        fixtures = ROOT / 'tests/runtime'
        shutil.copyfile(fixtures / 'RawTimingLog.cs.txt', reader / 'Program.cs')
        shutil.copyfile(fixtures / 'Inventory.csproj.txt', reader / 'Reader.csproj')
        run(DOTNET, 'build', reader / 'Reader.csproj', '-c', 'Release', '-p:UseSharedCompilation=false')
        report, cache = base / 'report.json', base / 'cache'

        def products(workspace):
            return {str(p.relative_to(workspace)): p.read_bytes() for folder in ['P0', 'P1', 'App', 'Unrelated']
                    for tree in ['bin/Release', 'obj/Release'] for p in (workspace / folder / tree).rglob('*')
                    if p.is_file() and p.suffix in ['.dll', '.pdb', '.resources']}

        def build(label, misses, value, raw_compilers=None):
            for folder in ['P0', 'P1', 'App', 'Unrelated']:
                for tree in ['bin/Release', 'obj/Release']:
                    shutil.rmtree(root / folder / tree, ignore_errors=True)
            run(DOTNET, RUNNER, 'action', root, manifest, report, cache)
            result = json.loads(report.read_text())
            observed = run(DOTNET, root / 'App/bin/Release/net10.0/App.dll').stdout.strip()
            assert observed == value, (label, observed, value)
            binlog = base / (label + '.binlog')
            run(DOTNET, driver / 'bin/Release/net10.0/Raw.dll', raw, manifest, 'build', binlog)
            compiled = json.loads(run(DOTNET, reader / 'bin/Release/net10.0/Reader.dll', binlog).stdout)['compiled']
            print(json.dumps({'case': label, 'graphMisses': result['misses'], 'rawCompilerProjects': [c['project'] for c in compiled], 'referenceSha256': hashlib.sha256((root / 'P0/obj/Release/net10.0/ref/P0.dll').read_bytes()).hexdigest()}), flush=True)
            assert (result['hits'], result['misses']) == (4 - misses, misses), result
            expected = misses if raw_compilers is None else raw_compilers
            assert len(compiled) == expected, (label, compiled)
            assert products(root) == products(raw), label
            return products(root)

        original_value = 'shared-one/resource-one/metadata-one/property-one;shared-one'
        baseline = build('seed', 4, original_value)
        assert baseline == build('replay', 0, original_value)
        cases = [('shared-source', 'Shared/Code.cs', 'shared-one', 'shared-two', 2, 2),
                 ('resource', 'P0/Resource.resx', 'resource-one', 'resource-two', 2, 1),
                 ('generated-metadata', 'P0/meta.txt', 'metadata-one', 'metadata-two', 2, 1),
                 ('imported-property', 'P0/Options.props', 'property-one', 'property-two', 2, 1)]
        for label, path, before, after, misses, raw_compilers in cases:
            original = (root / path).read_bytes()
            assert original.count(before.encode()) == 1
            for workspace in [root, raw]:
                (workspace / path).write_bytes(original.replace(before.encode(), after.encode()))
            # Noncompiler dependency contracts deliberately propagate resources,
            # generator inputs and imports. Record the conservative consumer miss
            # separately from raw compilation; never claim equal boundaries here.
            if label == 'imported-property':
                rejected = run(DOTNET, RUNNER, 'action', root, manifest, report, cache, success=False)
                assert 'Graph definition changed; rerun sync: P0/Options.props' in rejected.stderr
                run(DOTNET, sync, root, SDK / 'sdk/10.0.400', 'App/App.csproj', 'Unrelated/Unrelated.csproj', '--mappings', mapping)
            changed = build(label, misses, original_value.replace(before, after), raw_compilers)
            assert changed['Unrelated/bin/Release/net10.0/Unrelated.dll'] == baseline['Unrelated/bin/Release/net10.0/Unrelated.dll']
            assert changed['App/bin/Release/net10.0/App.dll'] == baseline['App/bin/Release/net10.0/App.dll']
            assert changed['P0/obj/Release/net10.0/ref/P0.dll'] == baseline['P0/obj/Release/net10.0/ref/P0.dll']
            for workspace in [root, raw]:
                (workspace / path).write_bytes(original)
            if label == 'imported-property':
                run(DOTNET, sync, root, SDK / 'sdk/10.0.400', 'App/App.csproj', 'Unrelated/Unrelated.csproj', '--mappings', mapping)
            assert build(label + '-restored', misses if label == 'imported-property' else 0, original_value, raw_compilers=raw_compilers) == baseline
            print('PASS:', label, 'owner invalidation, unchanged consumer/reference bytes, current runtime value, raw byte parity and exact restoration', flush=True)


if __name__ == '__main__':
    main()
