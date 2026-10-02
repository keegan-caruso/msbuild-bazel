"""Web/Razor SDK sources and AssemblyAttribute keep their MSBuild semantics."""

import json
from pathlib import Path
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER, SDK, run


def main():
    with tempfile.TemporaryDirectory(prefix='graph-web-') as temporary:
        base = Path(temporary)
        root = base / 'workspace'
        root.mkdir()
        for name, sdk, extra in [('Views', 'Microsoft.NET.Sdk.Razor', '<AddRazorSupportForMvc>true</AddRazorSupportForMvc>'),
                                 ('App', 'Microsoft.NET.Sdk.Web', '')]:
            project = root / name
            project.mkdir()
            references = '<ProjectReference Include="../Views/Views.csproj" />' if name == 'App' else '<FrameworkReference Include="Microsoft.AspNetCore.App" />'
            (project / f'{name}.csproj').write_text(f'<Project Sdk="{sdk}"><PropertyGroup><TargetFramework>net10.0</TargetFramework>{extra}</PropertyGroup><ItemGroup>{references}'
                '<AssemblyAttribute Include="System.Reflection.AssemblyMetadataAttribute"><_Parameter1>probe</_Parameter1><_Parameter2>retained</_Parameter2></AssemblyAttribute></ItemGroup></Project>')
        (root / 'App/Program.cs').write_text('System.Console.WriteLine("web graph");')
        (root / 'Views/Page.cshtml').write_text('@{ var message = "first"; }<p>@message</p>')
        (root / 'Views/Marker.cs').write_text('public class Marker {}')
        run(DOTNET, ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll', root,
            SDK / 'sdk/10.0.400', 'App/App.csproj', '--graph')
        contract = root / 'graph.generated.json'
        report = base / 'report.json'
        def build(hits):
            for project in ['App', 'Views']:
                for directory in ['bin', 'obj']:
                    shutil.rmtree(root / project / directory, ignore_errors=True)
            run(DOTNET, RUNNER, 'action', root, contract, report, base / 'cache')
            result = json.loads(report.read_text())
            assert result['hits'] == hits, result
            assert run(DOTNET, root / 'App/bin/Release/net10.0/App.dll').stdout.strip() == 'web graph'
            return (root / 'Views/bin/Release/net10.0/Views.dll').read_bytes()
        original = build(0)
        assert build(2) == original
        (root / 'Views/Page.cshtml').write_text('@{ var message = "second"; }<p>@message</p>')
        assert build(0) != original
        print('PASS: Web/Razor graph compile, replay, Razor edit invalidation, AssemblyAttribute')


if __name__ == '__main__':
    main()
