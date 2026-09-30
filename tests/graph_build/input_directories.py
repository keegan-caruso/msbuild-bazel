"""Explicit directory existence preserves SDK discovery in fresh graph actions."""
import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-input-directories-') as temporary:
        base = Path(temporary).resolve()
        root = base / 'workspace'
        root.mkdir()
        (root / 'Web.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk.Web"><PropertyGroup>'
            '<TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings>'
            '</PropertyGroup></Project>')
        (root / 'Program.cs').write_text('var app = WebApplication.CreateBuilder(args).Build(); app.Run();')
        contract = {'Version': 4, 'Entry': 'Web.csproj', 'SdkVersion': '10.0.400',
            'Properties': {'Configuration': 'Release'}, 'SharedInputs': [], 'InputDirectories': ['wwwroot'],
            'Projects': {'Web.csproj': {'Inputs': ['Web.csproj', 'Program.cs'],
                'OutputDirectories': ['bin/Release/net10.0', 'obj/Release/net10.0']}}}
        manifest, report = base / 'contract.json', base / 'report.json'
        def build(failure=None):
            for directory in ['bin', 'obj']:
                shutil.rmtree(root / directory, ignore_errors=True)
            manifest.write_text(json.dumps(contract))
            result = run(DOTNET, RUNNER, 'action', root, manifest, report, base / 'cache', success=failure is None)
            if failure:
                assert failure in result.stderr, result.stderr
                return
            return json.loads(report.read_text())
        assert build()['hits'] == 0
        discovery = root / 'obj/Release/net10.0/staticwebassets.build.json'
        baseline = json.loads(discovery.read_text())
        assert any(p['ContentRoot'] == str(root / 'wwwroot') + '/' for p in baseline['DiscoveryPatterns'])
        (root / 'wwwroot').rmdir()
        assert build()['hits'] == 1
        assert json.loads(discovery.read_text()) == baseline
        run(DOTNET, 'msbuild', root / 'Web.csproj', '-graphBuild', '-t:Build', '-p:Configuration=Release', '-p:UseSharedCompilation=false')
        assert json.loads(discovery.read_text()) == baseline
        contract['InputDirectories'].append('other-empty')
        assert build()['hits'] == 0
        mapping = base / 'mapping.json'
        mapping.write_text(json.dumps({'projectDefaults': {'inputDirectories': ['wwwroot']}}))
        run(DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root,
            SDK / 'sdk/10.0.400', 'Web.csproj', '--graph', '--mappings', mapping)
        generated = json.loads((root / 'graph.generated.json').read_text())
        assert generated['Version'] == 4 and generated['InputDirectories'] == ['wwwroot']
        (root / 'graph.generated.json').unlink()
        (root / 'graph.generated.bzl').unlink()
        contract['InputDirectories'] = ['bin/Release/net10.0/empty']
        build('Input directory overlaps generated state')
        contract['InputDirectories'] = ['Program.cs']
        build('Expected input directory, found file')
        contract['InputDirectories'] = ['wwwroot']
        (root / 'wwwroot').rmdir()
        (root / 'wwwroot').symlink_to(root / 'other-empty', target_is_directory=True)
        build('Symlinks are not supported')
        (root / 'wwwroot').unlink()
        project = root / 'Web.csproj'
        project.write_text(project.read_text().replace('</Project>',
            '<Target Name="DeleteInputDirectory" AfterTargets="Build"><RemoveDir Directories="wwwroot" /></Target></Project>'))
        build('Declared input directory is missing')
        print('PASS: empty web root discovery, fresh replay/raw parity, directory-contract invalidation, generated mapping, ownership/file/link rejection and final existence check')


if __name__ == '__main__':
    main()
