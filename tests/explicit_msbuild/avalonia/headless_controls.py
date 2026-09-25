"""Small authored controls for the pinned source-built Headless integrations."""
from pathlib import Path


def install(source):
    entries = []
    template = Path(__file__).with_name('HeadlessSmoke.cs.txt').read_text()
    for framework in ['XUnit', 'NUnit']:
        name = 'Qualification.Headless.' + framework
        folder = source / 'tests' / name
        folder.mkdir()
        packages = '<Import Project="../../build/XUnit.props" />' if framework == 'XUnit' else '''<ItemGroup>
<PackageReference Include="NUnit" Version="3.13.3" />
<PackageReference Include="NUnit3TestAdapter" Version="4.4.2" />
<PackageReference Include="Microsoft.NET.Test.Sdk" Version="17.5.0" />
</ItemGroup>'''
        (folder/(name+'.csproj')).write_text('''<Project Sdk="Microsoft.NET.Sdk">
<PropertyGroup><TargetFramework>net8.0</TargetFramework><IsTestProject>true</IsTestProject><SignAssembly>false</SignAssembly><DefineConstants>$(DefineConstants);''' + framework.upper() + '''</DefineConstants></PropertyGroup>
<Import Project="../../build/UnitTests.NetCore.targets" />
''' + packages + '''
<ItemGroup>
<ProjectReference Include="../../src/Headless/Avalonia.Headless.''' + framework + '''/Avalonia.Headless.''' + framework + '''.csproj" />
<ProjectReference Include="../../src/Headless/Avalonia.Headless.Vnc/Avalonia.Headless.Vnc.csproj" />
<ProjectReference Include="../../src/Skia/Avalonia.Skia/Avalonia.Skia.csproj" />
<ProjectReference Include="../../src/Avalonia.Themes.Simple/Avalonia.Themes.Simple.csproj" />
</ItemGroup></Project>''')
        (folder/'Smoke.cs').write_text(template)
        entries.append((folder/(name+'.csproj')).relative_to(source).as_posix())
    return entries
