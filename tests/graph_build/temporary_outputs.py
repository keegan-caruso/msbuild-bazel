"""Declared task scratch is removed without hiding required products or inputs."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, fixture, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-temporary-outputs-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        project = root / 'Library.csproj'
        original = ('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework>'
                    '</PropertyGroup><Target Name="GenerateScratch" BeforeTargets="CoreCompile">'
                    '<MakeDir Directories="$(IntermediateOutputPath)temporary"/>'
                    '<WriteLinesToFile File="$(IntermediateOutputPath)temporary/$([System.Guid]::NewGuid()).txt" Lines="temporary"/>'
                    '</Target></Project>')
        project.write_text(original)
        (root / 'Code.cs').write_text('public class Library { public const int Value = 7; }')
        contract = {'Version': 5, 'Entry': 'Library.csproj', 'SdkVersion': '10.0.400',
                    'Properties': {'Configuration': 'Release'}, 'SharedInputs': [],
                    'TemporaryDirectories': ['obj/Release/net10.0/temporary'], 'InputDirectories': ['empty-input'],
                    'Projects': {'Library.csproj': {'Inputs': ['Library.csproj', 'Code.cs'],
                                'OutputDirectories': ['bin/Release/net10.0', 'obj/Release/net10.0']}}}
        manifest, report, cache = base / 'contract.json', base / 'report.json', base / 'cache'
        def build(failure=None):
            for directory in ['bin', 'obj/Release']:
                shutil.rmtree(root / directory, ignore_errors=True)
            manifest.write_text(json.dumps(contract))
            before = set(cache.glob('*/manifest.json'))
            result = run(DOTNET, RUNNER, 'action', root, manifest, report, cache, success=failure is None)
            if failure:
                assert failure in result.stderr, result.stderr
                assert set(cache.glob('*/manifest.json')) == before, 'Failure published a snapshot'
                return
            assert not (root / 'obj/Release/net10.0/temporary').exists()
            return json.loads(report.read_text())
        assert build()['temporaryDirectoriesRemoved'] == 1
        product = root / 'bin/Release/net10.0/Library.dll'
        baseline = hashlib.sha256(product.read_bytes()).hexdigest()
        replay = build()
        assert replay['hits'] == 1 and replay['temporaryDirectoriesRemoved'] == 0
        assert hashlib.sha256(product.read_bytes()).hexdigest() == baseline
        contract['TemporaryDirectories'] += ['obj/Release/net10.0/other-temporary']
        assert build()['misses'] == 1, 'Cleanup contract changes must invalidate replay'
        mapping = base / 'mapping.json'
        mapping.write_text(json.dumps({'projectDefaults': {
            'documents': {'Library.csproj': {'sha256': hashlib.sha256(project.read_bytes()).hexdigest(),
                           'targets': ['GenerateScratch'], 'tasks': [], 'inputs': []}},
            'temporaryDirectories': ['$(IntermediateOutputPath)temporary'], 'inputDirectories': ['empty-input']}}))
        run(DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root,
            SDK / 'sdk/10.0.400', 'Library.csproj', '--mappings', mapping)
        generated = json.loads((root / 'graph.generated.json').read_text())
        assert generated['Version'] == 5 and generated['TemporaryDirectories'] == ['obj/Release/net10.0/temporary']
        assert generated['InputDirectories'] == ['empty-input']
        (root / 'graph.generated.json').unlink()
        (root / 'graph.generated.bzl').unlink()
        contract['TemporaryDirectories'] = ['outside']
        build('strict child of an owned output')
        contract['TemporaryDirectories'] = ['obj/Release/net10.0']
        build('strict child of an owned output')
        contract['TemporaryDirectories'] = ['bin/Release/net10.0']
        build('strict child of an owned output')
        contract['TemporaryDirectories'] = ['obj/Release/net10.0/temporary']
        contract['Projects']['Library.csproj']['OutputFiles'] = ['obj/Release/net10.0/temporary/required.txt']
        build('overlaps an input or required product')
        del contract['Projects']['Library.csproj']['OutputFiles']
        for copied, producer in [('obj/Release/net10.0/temporary/copy.txt', 'bin/Release/net10.0/Library.dll'),
                                 ('bin/Release/net10.0/copy.txt', 'obj/Release/net10.0/temporary/producer.txt')]:
            contract['Projects']['Library.csproj']['DependencyCopies'] = {copied: producer}
            build('overlaps an input or required product')
        del contract['Projects']['Library.csproj']['DependencyCopies']
        contract['Projects']['Library.csproj']['Inputs'].append('obj/Release/net10.0/temporary/input.txt')
        path = root / 'obj/Release/net10.0/temporary/input.txt'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('protected')
        # Build's reset deletes ordinary outputs, so test constructor validation
        # directly with the protected input still in place.
        manifest.write_text(json.dumps(contract))
        result = run(DOTNET, RUNNER, 'action', root, manifest, report, cache, success=False)
        assert 'Output directory contains a declared input' in result.stderr, result.stderr
        contract['Projects']['Library.csproj']['Inputs'].pop()
        contract['Version'] = 4
        build('require graph contract version 5')
        contract['Version'] = 5
        project.write_text(original.replace('<Project Sdk=', '<Project InitialTargets="ReturnScratch" Sdk=').replace('</Project>',
            '<Target Name="ReturnScratch" Returns="@(Scratch)"><ItemGroup>'
            '<Scratch Include="obj/Release/net10.0/temporary/result.txt" />'
            '</ItemGroup></Target></Project>'))
        build('Target result references a temporary directory')
        project.write_text(original.replace('<Project Sdk=', '<Project InitialTargets="ReturnScratch" Sdk=').replace('</Project>',
            '<Target Name="ReturnScratch" Returns="@(Scratch)"><ItemGroup>'
            '<Scratch Include="ordinary"><DataPath>obj/Release/net10.0/temporary/result.txt</DataPath></Scratch>'
            '</ItemGroup></Target></Project>'))
        build('Target result references a temporary directory')
        project.write_text(original.replace('</Project>', '<Target Name="LinkScratch" AfterTargets="Build">'
            '<RemoveDir Directories="$(IntermediateOutputPath)temporary"/>'
            '<Exec Command="ln -s ../../Code.cs $(IntermediateOutputPath)temporary"/>'
            '</Target></Project>'))
        build('Symlinks are not supported')
        project.write_text(original.replace('</Project>', '<Target Name="ModifyInput" AfterTargets="Build">'
            '<WriteLinesToFile File="Code.cs" Lines="changed" Overwrite="true"/></Target></Project>'))
        build('Build modified a declared input')
        dependent_projects()
        print('PASS: scratch cleanup, full replay, contract invalidation, generated mapping, input/product/ownership/version/result rejection and unchanged input guard')


def dependent_projects():
    # Non-reference boundaries enumerate producer outputs before graph cleanup.
    # Scratch must never enter that cached enumeration or consumer fingerprints.
    with tempfile.TemporaryDirectory(prefix='graph-dependent-scratch-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        contract = fixture(root)
        contract['Version'] = 5
        contract['TemporaryDirectories'] = ['P0/obj/Release/net10.0/temporary']
        project = root / 'P0/P0.csproj'
        project.write_text(project.read_text().replace('</Project>',
            '<Target Name="Scratch" BeforeTargets="CoreCompile">'
            '<MakeDir Directories="$(IntermediateOutputPath)temporary"/>'
            '<WriteLinesToFile File="$(IntermediateOutputPath)temporary/$([System.Guid]::NewGuid()).txt" Lines="scratch"/>'
            '</Target></Project>'))
        manifest, report, cache = base / 'contract.json', base / 'report.json', base / 'cache'
        manifest.write_text(json.dumps(contract))
        for read in ['no-read', 'no-read', 'read']:
            for index in range(3):
                for directory in ['bin', 'obj/Release']:
                    shutil.rmtree(root / f'P{index}' / directory, ignore_errors=True)
            run(DOTNET, RUNNER, 'action', root, manifest, report, cache, 'Build', read)
            observed = json.loads(report.read_text())
            assert observed['hits'] == (3 if read == 'read' else 0), observed
            assert observed['misses'] == (0 if read == 'read' else 3), observed
            assert not (root / contract['TemporaryDirectories'][0]).exists()
        snapshots = [json.loads(path.read_text()) for path in cache.glob('*/manifest.json')]
        assert len(snapshots) == 3, 'Random scratch changed dependency fingerprints'
        assert all('/temporary/' not in path for snapshot in snapshots for path in snapshot['Files'])


if __name__ == '__main__':
    main()
