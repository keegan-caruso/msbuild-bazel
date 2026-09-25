"""Black-box MSBuild evaluation and BUILD synchronization controls."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DOTNET = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT / '.tools/dotnet')).resolve()
DLL = ROOT / 'tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll'
SDK = DOTNET / 'sdk/10.0.400'


class ProjectSyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.put('Directory.Build.props', '<Project><Import Project="Shared.props"/><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
        self.put('Shared.props', '<Project><PropertyGroup><Nullable>enable</Nullable></PropertyGroup></Project>')
        self.put('Directory.Build.targets', '<Project><PropertyGroup><LangVersion>latest</LangVersion></PropertyGroup></Project>')
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"/>')
        self.put('Core/Core.cs', 'public class Core {}')

    def put(self, path, text):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def run_sync(self, *args, success=True):
        result = subprocess.run([str(DOTNET / 'dotnet'), str(DLL), str(self.root), str(SDK), *args], text=True, capture_output=True)
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result.stderr

    def test_imports_references_and_check(self):
        self.put('App/App.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Core/Core.csproj"/></ItemGroup></Project>')
        self.put('App/Program.cs', 'System.Console.WriteLine(typeof(Core).Name);')
        self.run_sync('App/App.csproj')
        output = (self.root / 'BUILD.bazel').read_text()
        for fragment in ['"Directory.Build.props"', '"Shared.props"', '"Directory.Build.targets"', '"Core/Core.cs"', '":Core_Core"', 'msbuild_binary(', '"nullable": "enable"']:
            self.assertIn(fragment, output)
        self.run_sync('App/App.csproj', '--check')
        self.put('Shared.props', '<Project><PropertyGroup><Nullable>disable</Nullable></PropertyGroup></Project>')
        self.assertIn('stale', self.run_sync('App/App.csproj', '--check', success=False))
        self.assertEqual(output, (self.root / 'BUILD.bazel').read_text())
        self.run_sync('App/App.csproj')
        self.assertIn('"nullable": "disable"', (self.root / 'BUILD.bazel').read_text())
        self.put('Core/Added.cs', 'class Added {}')
        self.assertIn('stale', self.run_sync('App/App.csproj', '--check', success=False))

    def test_framework_condition_and_removal(self):
        self.put('Core/Core.csproj', '''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework/><TargetFrameworks>net9.0;net10.0</TargetFrameworks></PropertyGroup><ItemGroup Condition="'$(TargetFramework)' == 'net9.0'"><Compile Remove="Modern.cs"/></ItemGroup></Project>''')
        self.put('Core/Modern.cs', 'class Modern {}')
        self.run_sync('Core/Core.csproj')
        output = (self.root / 'BUILD.bazel').read_text()
        self.assertEqual(output.count('Core/Modern.cs'), 1)
        self.assertIn('"net9.0"', output)
        self.assertIn('"net10.0"', output)

    def test_rejections_preserve_output(self):
        self.run_sync('Core/Core.csproj')
        original = (self.root / 'BUILD.bazel').read_text()
        for xml, error in [
            ('<ItemGroup><PackageReference Include="Example" Version="1.0.0"/></ItemGroup>', 'PackageReference'),
            ('<Target Name="Generate" BeforeTargets="CoreCompile"/>', 'Custom targets'),
            ('<PropertyGroup><IsTestProject>true</IsTestProject></PropertyGroup>', 'Test project'),
            ('<ItemGroup><Content Include="data.json"/></ItemGroup>', 'Content'),
            ('<ItemGroup><CustomInput Include="data.json"/></ItemGroup>', 'explicit mapping'),
        ]:
            self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk">' + xml + '</Project>')
            self.assertIn(error, self.run_sync('Core/Core.csproj', success=False))
            self.assertEqual(original, (self.root / 'BUILD.bazel').read_text())

    def test_authored_build_is_preserved(self):
        self.put('BUILD.bazel', '# authored\n')
        self.assertIn('authored', self.run_sync('Core/Core.csproj', success=False))
        self.assertEqual('# authored\n', (self.root / 'BUILD.bazel').read_text())

    def test_cycle_is_rejected(self):
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><ProjectReference Include="Core.csproj"/></ItemGroup></Project>')
        self.assertIn('cycle', self.run_sync('Core/Core.csproj', success=False))
        self.assertFalse((self.root / 'BUILD.bazel').exists())

    def test_generated_restore_imports_are_not_inputs(self):
        self.put('Core/obj/Core.csproj.nuget.g.props', '<Project><Target Name="StaleRestore"/></Project>')
        self.run_sync('Core/Core.csproj')
        self.assertNotIn('obj/', (self.root / 'BUILD.bazel').read_text())

    def test_nested_packages_and_missing_sources(self):
        self.put('Core/BUILD.bazel', '# authored package')
        self.assertIn('Nested Bazel package', self.run_sync('Core/Core.csproj', success=False))
        (self.root / 'Core/BUILD.bazel').unlink()
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><Compile Include="Generated.cs"/></ItemGroup></Project>')
        self.assertIn('generator binding', self.run_sync('Core/Core.csproj', success=False))
