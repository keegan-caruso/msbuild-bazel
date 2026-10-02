"""SDK resource state is regenerated; actual resources and explicit outputs replay."""
import json
from pathlib import Path
import shutil
import tempfile
from qualify import DOTNET, ENV, RUNNER, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-resource-state-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        contract = fixture(root)
        project = root / 'P0/P0.csproj'
        project.write_text(project.read_text().replace('</Project>', '<ItemGroup><EmbeddedResource Include="Resource.resx" /></ItemGroup>'
            '<PropertyGroup><EnableDefaultEmbeddedResourceItems>false</EnableDefaultEmbeddedResourceItems></PropertyGroup>'
            '<Target Name="ExplicitCache" AfterTargets="Build"><WriteLinesToFile File="$(OutputPath)custom.GenerateResource.cache" Lines="owned" Overwrite="true" /></Target></Project>'))
        (root / 'P0/Code.cs').write_text('public class P0 { public static int Value() => int.Parse(new System.Resources.ResourceManager("P0.Resource", typeof(P0).Assembly).GetString("Value")!); }')
        resource = root / 'P0/Resource.resx'
        resource.write_text('<root><resheader name="resmimetype"><value>text/microsoft-resx</value></resheader>'
            '<resheader name="version"><value>2.0</value></resheader><data name="Value" xml:space="preserve"><value>1</value></data></root>')
        contract['Projects']['P0/P0.csproj']['Inputs'] += ['P0/Resource.resx']
        owned = 'P0/bin/Release/net10.0/custom.GenerateResource.cache'
        contract['Projects']['P0/P0.csproj']['OutputFiles'] = [owned]
        path = base / 'contract.json'
        path.write_text(json.dumps(contract))
        report = base / 'report.json'
        cache = base / 'cache'
        command = [DOTNET, RUNNER, 'action', root, path, report, cache]
        state = root / 'P0/obj/Release/net10.0/P0.csproj.GenerateResource.cache'
        def clear():
            for name in ['P0', 'P1', 'P2']:
                for directory in ['bin', 'obj']:
                    shutil.rmtree(root / name / directory, ignore_errors=True)
        def build(hits, value):
            clear()
            run(*command)
            assert json.loads(report.read_text())['hits'] == hits
            result = run(DOTNET, root / 'P2/bin/Release/net10.0/P2.dll')
            assert result.stdout.strip() == str(value), result.stdout
            assert (root / owned).read_text().strip() == 'owned'
        build(0, 1)
        assert state.exists(), 'SDK should generate dependency state on a miss'
        before = (root / 'P0/bin/Release/net10.0/P0.dll').read_bytes()
        manifests = [json.loads(p.read_text()) for p in cache.glob('*/manifest.json')]
        assert all('P0/obj/Release/net10.0/P0.csproj.GenerateResource.cache' not in p['Files'] for p in manifests)
        build(3, 1)
        assert not state.exists(), 'Cache hits do not need SDK resource state'
        assert (root / 'P0/bin/Release/net10.0/P0.dll').read_bytes() == before
        resource.write_text(resource.read_text().replace('<value>1</value>', '<value>2</value>'))
        build(0, 2)
        assert state.exists(), 'Changed resources must regenerate dependency state'
        assert (root / 'P0/bin/Release/net10.0/P0.dll').read_bytes() != before
        build(3, 2)
        print('PASS: resource invalidation, state recreation, runtime values and explicit cache-named outputs')


if __name__ == '__main__':
    main()
