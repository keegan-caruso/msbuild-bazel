"""Black-box MSBuild evaluation and BUILD synchronization controls."""
import os
import json
import hashlib
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
        output = (self.root / 'projects.generated.bzl').read_text()
        for fragment in ['"Directory.Build.props"', '"Shared.props"', '"Directory.Build.targets"', '"Core/Core.cs"', '":Core_Core"', 'msbuild_binary(', '"nullable": "enable"']:
            self.assertIn(fragment, output)
        self.run_sync('App/App.csproj', '--check')
        self.put('Shared.props', '<Project><PropertyGroup><Nullable>disable</Nullable></PropertyGroup></Project>')
        self.assertIn('stale', self.run_sync('App/App.csproj', '--check', success=False))
        self.assertEqual(output, (self.root / 'projects.generated.bzl').read_text())
        self.run_sync('App/App.csproj')
        self.assertIn('"nullable": "disable"', (self.root / 'projects.generated.bzl').read_text())
        self.put('Core/Added.cs', 'class Added {}')
        self.assertIn('stale', self.run_sync('App/App.csproj', '--check', success=False))

    def test_framework_condition_and_removal(self):
        self.put('Core/Core.csproj', '''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework/><TargetFrameworks>net9.0;net10.0</TargetFrameworks></PropertyGroup><ItemGroup Condition="'$(TargetFramework)' == 'net9.0'"><Compile Remove="Modern.cs"/></ItemGroup></Project>''')
        self.put('Core/Modern.cs', 'class Modern {}')
        self.run_sync('Core/Core.csproj')
        output = (self.root / 'projects.generated.bzl').read_text()
        self.assertEqual(output.count('Core/Modern.cs'), 1)
        self.assertIn('"net9.0"', output)
        self.assertIn('"net10.0"', output)

    def test_rejections_preserve_output(self):
        self.run_sync('Core/Core.csproj')
        original = (self.root / 'projects.generated.bzl').read_text()
        for xml, error in [
            ('<ItemGroup><PackageReference Include="Example" Version="1.0.0"/></ItemGroup>', 'PackageReference'),
            ('<Target Name="Generate" BeforeTargets="CoreCompile"/>', 'Custom targets'),
            ('<PropertyGroup><IsTestProject>true</IsTestProject></PropertyGroup>', 'Test project'),
            ('<ItemGroup><Content Include="data.json"/></ItemGroup>', 'generator binding'),
            ('<ItemGroup><CustomInput Include="data.json"/></ItemGroup>', 'explicit mapping'),
        ]:
            self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk">' + xml + '</Project>')
            self.assertIn(error, self.run_sync('Core/Core.csproj', success=False))
            self.assertEqual(original, (self.root / 'projects.generated.bzl').read_text())

    def test_authored_build_is_preserved(self):
        self.put('BUILD.bazel', '# authored\n')
        self.run_sync('Core/Core.csproj')
        self.assertEqual('# authored\n', (self.root / 'BUILD.bazel').read_text())
        self.put('projects.generated.bzl', '# authored\n')
        self.assertIn('authored', self.run_sync('Core/Core.csproj', success=False))
        self.assertEqual('# authored\n', (self.root / 'projects.generated.bzl').read_text())

    def test_cycle_is_rejected(self):
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><ProjectReference Include="Core.csproj"/></ItemGroup></Project>')
        self.assertIn('cycle', self.run_sync('Core/Core.csproj', success=False))
        self.assertFalse((self.root / 'projects.generated.bzl').exists())

    def test_generated_restore_imports_are_not_inputs(self):
        self.put('Core/obj/Core.csproj.nuget.g.props', '<Project><Target Name="StaleRestore"/></Project>')
        self.run_sync('Core/Core.csproj')
        self.assertNotIn('obj/', (self.root / 'projects.generated.bzl').read_text())

    def test_nested_packages_and_missing_sources(self):
        self.put('Core/BUILD.bazel', '# authored package')
        self.assertIn('Nested Bazel package', self.run_sync('Core/Core.csproj', success=False))
        (self.root / 'Core/BUILD.bazel').unlink()
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><Compile Include="Generated.cs"/></ItemGroup></Project>')
        self.assertIn('generator binding', self.run_sync('Core/Core.csproj', success=False))

    def test_explicit_package_and_test_bindings(self):
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><IsTestProject>true</IsTestProject></PropertyGroup><ItemGroup><PackageReference Include="Example" Version="1.2.3"/></ItemGroup></Project>')
        mapping = dict(packages={'Example/1.2.3':dict(label='//packages:example',roles=['deps','build_deps'],analyzers=['//packages:analyzer'])},tests={'Core/Core.csproj':dict(protocol='vstest',runner='//tools:runner',adapters=['//tools:adapter'])})
        self.put('sync.json', json.dumps(mapping))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        output = (self.root/'projects.generated.bzl').read_text()
        for fragment in ['msbuild_test_project(', '//packages:example', '//packages:analyzer', '//tools:runner', '//tools:adapter', '"build_deps"']:
            self.assertIn(fragment, output)
        mapping['tests']['Core/Core.csproj']['environment']={'CASE':'changed'}
        self.put('sync.json', json.dumps(mapping))
        self.assertIn('stale', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', '--check', success=False))
        mapping['packages'] = {'Example/9.9.9':mapping['packages']['Example/1.2.3']}
        self.put('sync.json', json.dumps(mapping))
        self.assertIn('exact package mapping', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))
        self.assertEqual(output, (self.root/'projects.generated.bzl').read_text())

    def test_central_version_mapping(self):
        self.put('Directory.Packages.props', '<Project><PropertyGroup><ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally></PropertyGroup><ItemGroup><PackageVersion Include="Example" Version="1.2.3"/></ItemGroup></Project>')
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><PackageReference Include="Example"/></ItemGroup></Project>')
        self.put('sync.json', json.dumps(dict(packages={'Example/1.2.3':dict(label='//packages:example',roles=['deps'])})))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        output = (self.root/'projects.generated.bzl').read_text()
        self.assertIn('Directory.Packages.props', output)
        self.assertIn('//packages:example', output)

    def test_mapping_validation(self):
        cases = [
            (dict(typo={}), 'could not be mapped'),
            (dict(packages={'Example/1':dict(label='not-a-label',roles=['deps'])}), 'Bazel label'),
            (dict(packages={'Example/1':dict(label='//packages:example',roles=[])}), 'explicit deps'),
            (dict(tests={'Core/Core.csproj':dict(protocol='vstest')}), 'Bazel label'),
            (dict(tests={'Core/Core.csproj':dict(protocol='mtp',runner='//tools:runner')}), 'VSTest-only'),
            (dict(tests={'Missing.csproj':dict(protocol='executable')}), 'reachable project'),
        ]
        for mapping, message in cases:
            self.put('sync.json', json.dumps(mapping))
            self.assertIn(message, self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))

    def test_executable_test_mapping(self):
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup></Project>')
        self.put('sync.json', json.dumps(dict(tests={'Core/Core.csproj':dict(protocol='executable')})))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        self.assertIn('"test_protocol": "executable"', (self.root/'projects.generated.bzl').read_text())

    def test_mapped_properties_are_evaluated(self):
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><AssemblyName>Custom.Name</AssemblyName></PropertyGroup><ItemGroup Condition="\'$(IncludeExtra)\' != \'true\'"><Compile Remove="Extra.cs"/></ItemGroup></Project>')
        self.put('Core/Extra.cs', 'public class Extra {}')
        self.put('sync.json', json.dumps(dict(tests={'Core/Core.csproj':dict(protocol='executable',outputType='exe',properties={'IncludeExtra':'true'})})))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        output = (self.root/'projects.generated.bzl').read_text()
        self.assertIn('Core/Extra.cs', output)
        self.assertIn('Custom.Name', output)
        self.assertIn('"test_output_type": "exe"', output)

    def test_project_properties_and_framework_subset(self):
        self.put('Core/Core.csproj', '''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework/><TargetFrameworks>net9.0;net10.0</TargetFrameworks></PropertyGroup><ItemGroup Condition="'$(Flavor)' != 'extra'"><Compile Remove="Extra.cs"/></ItemGroup></Project>''')
        self.put('Core/Extra.cs', 'class Extra {}')
        self.put('sync.json', json.dumps(dict(projects={'Core/Core.csproj':dict(targetFrameworks=['net10.0'],properties={'Flavor':'extra'})})))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        output = (self.root/'projects.generated.bzl').read_text()
        self.assertIn('Core/Extra.cs', output)
        self.assertIn('"Flavor":"extra"', output)
        self.assertNotIn('net9.0', output)
        self.put('sync.json', json.dumps(dict(projects={'Core/Core.csproj':dict(targetFrameworks=['net8.0'])})))
        self.assertIn('not declared', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))
        self.assertEqual(output, (self.root/'projects.generated.bzl').read_text())

    def test_project_property_and_mapping_rejections(self):
        for mapping, error in [
            ({'Core/Core.csproj':dict(properties={'TargetFramework':'net9.0'})}, 'reserved'),
            ({'Core/Core.csproj':dict(properties={'Flavor':'a', 'flavor':'b'})}, 'Duplicate'),
            ({'Core/Core.csproj':dict(targetFrameworks=['net10.0','net10.0'])}, 'distinct'),
            ({'Core/Core.csproj':dict(targetFrameworks=['NET10.0'])}, 'lowercase'),
            ({'Missing.csproj':dict(properties={})}, 'reachable'),
        ]:
            self.put('sync.json', json.dumps(dict(projects=mapping)))
            self.assertIn(error, self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))
        self.put('sync.json', json.dumps(dict(projects={'Core/Core.csproj':dict(properties={'Flavor':'a'})}, tests={'Core/Core.csproj':dict(protocol='executable',outputType='exe',properties={'Flavor':'b'})})))
        self.assertIn('Conflicting', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))

    def test_project_and_test_properties_are_combined(self):
        self.put('sync.json', json.dumps(dict(projects={'Core/Core.csproj':dict(properties={'Flavor':'a'})}, tests={'Core/Core.csproj':dict(protocol='executable',outputType='exe',properties={'TestMode':'yes'})})))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        output = (self.root/'projects.generated.bzl').read_text()
        self.assertIn('"Flavor":"a"', output)
        self.assertIn('"TestMode":"yes"', output)

    def test_linked_sources_and_resources(self):
        self.put('Shared/Shared.cs', 'class Shared {}')
        self.put('Core/message.txt', 'hello')
        self.put('Core/options.txt', 'options')
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><Compile Include="../Shared/Shared.cs" Link="Shared/Shared.cs"/><EmbeddedResource Include="message.txt" LogicalName="Probe.Message" Language="CSharp" SubType="Designer"/><AdditionalFiles Include="options.txt"/><None Update="options.txt" CopyToOutputDirectory="PreserveNewest"/></ItemGroup></Project>')
        self.run_sync('Core/Core.csproj')
        output = (self.root/'projects.generated.bzl').read_text()
        for fragment in ['item_type = "Compile"', '"Link":"Shared/Shared.cs"', 'item_type = "EmbeddedResource"', '"LogicalName":"Probe.Message"', '"Language":"CSharp"', '"SubType":"Designer"', 'item_type = "AdditionalFiles"', '"CopyToOutputDirectory":"PreserveNewest"']:
            self.assertIn(fragment, output)
        self.run_sync('Core/Core.csproj', '--check')
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><EmbeddedResource Include="message.txt" LogicalName="Probe.Changed"/></ItemGroup></Project>')
        self.assertIn('stale', self.run_sync('Core/Core.csproj', '--check', success=False))
        self.assertEqual(output, (self.root/'projects.generated.bzl').read_text())

    def test_compile_order_matches_evaluation(self):
        self.put('Core/Second.cs', 'partial class Core {}')
        self.put('Core/First.cs', 'partial class Core {}')
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup><ItemGroup><Compile Include="Second.cs;First.cs"/></ItemGroup></Project>')
        self.run_sync('Core/Core.csproj')
        output = (self.root / 'projects.generated.bzl').read_text()
        self.assertIn('"srcs": ["Core/Second.cs","Core/First.cs"]', output)
        self.run_sync('Core/Core.csproj', '--check')

    def test_unsupported_item_metadata_is_rejected(self):
        for item, metadata in [('Compile', 'Custom'), ('EmbeddedResource', 'GenerateSource')]:
            self.put('Core/Core.csproj', f'<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><{item} Update="Core.cs" {metadata}="true"/></ItemGroup></Project>' if item == 'Compile' else f'<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><{item} Include="Core.cs" {metadata}="true"/></ItemGroup></Project>')
            self.assertIn('metadata requires explicit', self.run_sync('Core/Core.csproj', success=False))

    def test_private_package_metadata(self):
        self.put('sync.json', json.dumps(dict(packages={'Example/1.2.3':dict(label='//packages:example',roles=['deps'])})))
        for privacy in ['All', 'none']:
            self.put('Core/Core.csproj', f'<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><PackageReference Include="Example" Version="1.2.3" PrivateAssets="{privacy}" IsImplicitlyDefined="false" GeneratePathProperty="true"/></ItemGroup></Project>')
            self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
            self.assertIn('"Example":"'+privacy.lower()+'"', (self.root/'projects.generated.bzl').read_text())
        original = (self.root/'projects.generated.bzl').read_text()
        for metadata in ['PrivateAssets="invalid"', 'ExcludeAssets="invalid"', 'GeneratePathProperty="maybe"', 'VersionOverride="2.0.0"']:
            self.put('Core/Core.csproj', f'<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><PackageReference Include="Example" Version="1.2.3" {metadata}/></ItemGroup></Project>')
            self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False)
            self.assertEqual(original, (self.root/'projects.generated.bzl').read_text())

    def test_inherited_item_metadata(self):
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemDefinitionGroup><Compile><LinkBase>Shared</LinkBase></Compile></ItemDefinitionGroup></Project>')
        self.run_sync('Core/Core.csproj')
        self.assertIn('"LinkBase":"Shared/"', (self.root/'projects.generated.bzl').read_text())
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemDefinitionGroup><Compile><Custom>true</Custom></Compile></ItemDefinitionGroup></Project>')
        self.assertIn('metadata requires explicit', self.run_sync('Core/Core.csproj', success=False))

    def test_invalid_inherited_package_metadata_is_not_silently_ignored(self):
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemDefinitionGroup><PackageReference><ExcludeAssets>invalid</ExcludeAssets></PackageReference></ItemDefinitionGroup><ItemGroup><PackageReference Include="Example" Version="1.2.3"/></ItemGroup></Project>')
        self.put('sync.json', json.dumps(dict(packages={'Example/1.2.3':dict(label='//packages:example',roles=['deps'])})))
        self.assertIn('ExcludeAssets', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))

    def test_declared_bootstrap_view(self):
        runfiles = self.root/'runfiles'
        self.put('runfiles/generated.props', '<Project><PropertyGroup><Nullable>disable</Nullable></PropertyGroup></Project>')
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><Import Project="../generated.props"/></Project>')
        manifest = dict(inputs=[dict(path='generated.props',label=':bootstrap',runfile='generated.props')],packages=[],packageLock=None)
        self.put('inputs.json', json.dumps(manifest))
        self.run_sync('Core/Core.csproj', '--inputs', str(self.root/'inputs.json'), '--runfiles', str(runfiles))
        text=(self.root/'projects.generated.bzl').read_text()
        self.assertIn('":bootstrap":"generated.props"', text)
        self.assertNotIn('msbuild-sync-', text)
        self.assertFalse((self.root/'generated.props').exists())
        original=text
        for path in ['../outside.props','Core/Core.csproj']:
            manifest['inputs'][0]['path']=path;self.put('inputs.json',json.dumps(manifest))
            self.run_sync('Core/Core.csproj','--inputs',str(self.root/'inputs.json'),'--runfiles',str(runfiles),success=False)
            self.assertEqual(original,(self.root/'projects.generated.bzl').read_text())

    def test_analyzer_config_and_content_paths(self):
        self.put('Core/rules.globalconfig', 'is_global = true\n')
        self.put('NuGet.config', '<configuration/>')
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><EditorConfigFiles Include="rules.globalconfig"/><Content Include="../NuGet.config" Link="NuGet.config" CopyToOutputDirectory="PreserveNewest" Visible="false" Pack="true"/></ItemGroup></Project>')
        mapping = dict(projects={'Core/Core.csproj': dict(itemPaths={'NuGet.config': 'data/NuGet.config'})})
        self.put('sync.json', json.dumps(mapping))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        output = (self.root/'projects.generated.bzl').read_text()
        self.assertIn('"EditorConfigFiles"', output)
        self.assertIn('":NuGet.config":"data/NuGet.config"', output)
        self.assertIn('"Visible":"false"', output)
        mapping['projects']['Core/Core.csproj']['itemPaths'] = {'missing.txt': 'data/missing.txt'}
        self.put('sync.json', json.dumps(mapping))
        self.assertIn('does not match evaluated', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))
        (self.root/'Core/rules.globalconfig').unlink()
        self.assertIn('Missing input', self.run_sync('Core/Core.csproj', success=False))

    def test_package_reference_asset_roles(self):
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><Reference Include="Analyzer.Package" PrivateAssets="all" ExcludeAssets="compile"/></ItemGroup></Project>')
        mapping = dict(projects={'Core/Core.csproj': dict(references={'Analyzer.Package': dict(role='package', label=':analyzer', roles=['build_deps', 'analyzers'])})})
        self.put('sync.json', json.dumps(mapping))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        output = (self.root/'projects.generated.bzl').read_text()
        self.assertIn('"build_deps": [":analyzer"]', output)
        self.assertIn('"analyzers": [":analyzer"]', output)
        self.assertIn('"Analyzer.Package":"all"', output)
        mapping['projects']['Core/Core.csproj']['references']['Analyzer.Package']['role'] = 'compile'
        self.put('sync.json', json.dumps(mapping))
        self.assertIn('asset roles require', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))

    def test_project_platform_controls_evaluation_and_build(self):
        self.put('Core/Arm.cs', 'class Arm {}')
        self.put('Core/Core.csproj', '''<Project Sdk="Microsoft.NET.Sdk"><ItemGroup Condition="'$(Platform)' != 'arm64'"><Compile Remove="Arm.cs"/></ItemGroup></Project>''')
        self.run_sync('Core/Core.csproj')
        self.assertNotIn('Core/Arm.cs', (self.root/'projects.generated.bzl').read_text())
        self.put('sync.json', json.dumps(dict(projects={'Core/Core.csproj': dict(platform='arm64')})))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        output = (self.root/'projects.generated.bzl').read_text()
        self.assertIn('"Platform":"arm64"', output)
        self.assertIn('Core/Arm.cs', output)
        self.assertIn('stale', self.run_sync('Core/Core.csproj', '--check', success=False))
        self.assertEqual(output, (self.root/'projects.generated.bzl').read_text())

    def test_project_reference_item_outputs_are_explicit(self):
        self.put('Contract/Contract.csproj', '<Project Sdk="Microsoft.NET.Sdk"/>')
        self.put('Contract/Contract.cs', 'public class Contract {}')
        text = '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><ProjectReference Include="../Contract/Contract.csproj" ReferenceOutputAssembly="false" OutputItemType="ContractSources" Targets="SourceFilesProjectOutputGroup"/></ItemGroup></Project>'
        self.put('Core/Core.csproj', text)
        binding = dict(role='items', labels=[':contract_sources'], outputItemType='ContractSources', targets='SourceFilesProjectOutputGroup')
        mapping = dict(projects={'Core/Core.csproj': dict(projectReferences={'Contract/Contract.csproj': binding})})
        self.put('sync.json', json.dumps(mapping))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        output = (self.root/'projects.generated.bzl').read_text()
        self.assertIn('"items": [":contract_sources"]', output)
        self.assertIn('"deps": []', output)
        for before, after in [('SourceFilesProjectOutputGroup', 'Build'), ('ContractSources', 'OtherSources'), ('ReferenceOutputAssembly="false"', 'ReferenceOutputAssembly="true"')]:
            self.put('Core/Core.csproj', text.replace(before, after))
            self.assertIn('disagrees', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))
            self.assertEqual(output, (self.root/'projects.generated.bzl').read_text())

    def test_package_qualified_reference_paths(self):
        self.put('runfiles/example/ref/net8.0/Example.dll', 'evaluation-only fixture')
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><Reference Include="$(MSBuildProjectDirectory)/../.nuget/packages/example/1.0.0/ref/net8.0/Example.dll"/></ItemGroup></Project>')
        manifest = dict(inputs=[], packages=[dict(id='Example', version='1.0.0', runfile='example')], packageLock=':lock')
        self.put('inputs.json', json.dumps(manifest))
        binding = dict(packageReferencePaths={'example': ['ref/net8.0/Example.dll']}, transitiveCompileReferences=False)
        self.put('sync.json', json.dumps(dict(projects={'Core/Core.csproj': binding})))
        args = ['Core/Core.csproj', '--mappings', 'sync.json', '--inputs', str(self.root/'inputs.json'), '--runfiles', str(self.root/'runfiles')]
        self.run_sync(*args)
        output = (self.root/'projects.generated.bzl').read_text()
        self.assertIn('"package_reference_paths": {"example":["ref/net8.0/Example.dll"]}', output)
        self.assertIn('"reference_packages": []', output)
        self.assertIn('"transitive_compile_references": False', output)
        self.assertNotIn(str(self.root), output)
        self.run_sync(*args, '--check')
        for path in ['../outside.dll', '/outside.dll', 'ref/../outside.dll']:
            binding['packageReferencePaths']['example'] = [path]
            self.put('sync.json', json.dumps(dict(projects={'Core/Core.csproj': binding})))
            self.assertIn('safe relative', self.run_sync(*args, success=False))
            self.assertEqual(output, (self.root/'projects.generated.bzl').read_text())

    def test_locked_sdk_signing_key(self):
        self.put('runfiles/sdk/key.snk', 'fixture-key')
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><AssemblyOriginatorKeyFile>../.nuget/packages/example.sdk/1.0.0/key.snk</AssemblyOriginatorKeyFile></PropertyGroup></Project>')
        manifest = dict(inputs=[], packages=[dict(id='Example.Sdk',version='1.0.0',runfile='sdk')], packageLock=':lock')
        self.put('inputs.json', json.dumps(manifest))
        self.run_sync('Core/Core.csproj', '--inputs', str(self.root/'inputs.json'), '--runfiles', str(self.root/'runfiles'))
        output = (self.root/'projects.generated.bzl').read_text()
        self.assertIn('"package_lock": ":lock"', output)
        self.assertNotIn('key.snk', output)
        (self.root/'runfiles/sdk/key.snk').unlink()
        self.assertIn('Missing signing key', self.run_sync('Core/Core.csproj', '--inputs', str(self.root/'inputs.json'), '--runfiles', str(self.root/'runfiles'), success=False))

    def test_checked_in_generated_source_and_using(self):
        self.put('Core/Generated.cs', 'class Generated {}')
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><Compile Update="Generated.cs" DesignTime="True" AutoGen="True" DependentUpon="Generated.tt"/><Using Include="System.Math" Static="true"/><Using Include="System.String" Alias="Text"/></ItemGroup></Project>')
        self.run_sync('Core/Core.csproj')
        self.assertIn('Core/Generated.cs', (self.root/'projects.generated.bzl').read_text())
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><Using Include="System" Unknown="true"/></ItemGroup></Project>')
        self.assertIn('Unsupported Using metadata', self.run_sync('Core/Core.csproj', success=False))

    def test_explicit_assembly_selections(self):
        self.put('sync.json', json.dumps(dict(projects={'Core/Core.csproj': dict(assemblySelections=[':chosen'])})))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        self.assertIn('"assembly_selections": [":chosen"]', (self.root/'projects.generated.bzl').read_text())
        self.put('sync.json', json.dumps(dict(projects={'Core/Core.csproj': dict(assemblySelections=['not-a-label'])})))
        self.assertIn('label', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False).lower())

    def test_generated_test_settings(self):
        self.put('sync.json', json.dumps(dict(tests={'Core/Core.csproj': dict(protocol='vstest', runner=':runner', settingsOutput='.runsettings')})))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        self.assertIn('"test_settings_output": ".runsettings"', (self.root/'projects.generated.bzl').read_text())
        self.put('sync.json', json.dumps(dict(tests={'Core/Core.csproj': dict(protocol='vstest', runner=':runner', settings='a.runsettings', settingsOutput='.runsettings')})))
        self.assertIn('either settings', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))

    def test_explicit_reference_roles(self):
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><Reference Include="Other"/><ProjectReference Include="../Generator/Generator.csproj" OutputItemType="Analyzer" ReferenceOutputAssembly="false"/></ItemGroup></Project>')
        mapping=dict(projects={'Core/Core.csproj':dict(references={'Other':dict(role='compile',label=':other')},projectReferences={'Generator/Generator.csproj':dict(role='analyzer',label=':generator')})})
        self.put('sync.json',json.dumps(mapping));self.run_sync('Core/Core.csproj','--mappings','sync.json')
        text=(self.root/'projects.generated.bzl').read_text()
        self.assertIn('"reference_projects": {":other":"Other"}',text)
        self.assertIn('"analyzers": [":generator"]',text)
        mapping['projects']['Core/Core.csproj']['projectReferences']['Generator/Generator.csproj']['role']='compile'
        self.put('sync.json',json.dumps(mapping))
        self.assertIn('role disagrees',self.run_sync('Core/Core.csproj','--mappings','sync.json',success=False))

    def test_custom_document_contract(self):
        xml='<Project Sdk="Microsoft.NET.Sdk"><Target Name="Generate" BeforeTargets="CoreCompile"/></Project>'
        self.put('Core/Core.csproj',xml)
        mapping=dict(projects={'Core/Core.csproj':dict(documents={'Core/Core.csproj':dict(sha256=hashlib.sha256(xml.encode()).hexdigest(),targets=['Generate'],tasks=[],inputs=[])})})
        self.put('sync.json',json.dumps(mapping));self.run_sync('Core/Core.csproj','--mappings','sync.json')
        original=(self.root/'projects.generated.bzl').read_text()
        self.assertIn('# Contract Core/Core.csproj',original)
        mapping['projects']['Core/Core.csproj']['documents']['unused.targets'] = dict(sha256='0'*64, targets=[], tasks=[], inputs=[])
        self.put('sync.json',json.dumps(mapping))
        self.assertIn('does not match evaluated imports',self.run_sync('Core/Core.csproj','--mappings','sync.json',success=False))
        del mapping['projects']['Core/Core.csproj']['documents']['unused.targets']
        self.put('sync.json',json.dumps(mapping))
        self.put('Core/Core.csproj','<Project Sdk="Microsoft.NET.Sdk"/>')
        self.assertIn('contract changed',self.run_sync('Core/Core.csproj','--mappings','sync.json',success=False))
        self.put('Core/Core.csproj',xml+'\n')
        self.assertIn('contract changed',self.run_sync('Core/Core.csproj','--mappings','sync.json',success=False))
        self.assertEqual(original,(self.root/'projects.generated.bzl').read_text())

    def test_friend_and_signing_inputs(self):
        self.put('Core/key.snk','fixture-placeholder')
        self.put('Core/Core.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><AssemblyOriginatorKeyFile>key.snk</AssemblyOriginatorKeyFile></PropertyGroup><ItemGroup><InternalsVisibleTo Include="Friend"/></ItemGroup></Project>')
        self.run_sync('Core/Core.csproj')
        self.assertIn('Core/key.snk',(self.root/'projects.generated.bzl').read_text())
        (self.root/'Core/key.snk').unlink()
        self.assertIn('Missing signing key',self.run_sync('Core/Core.csproj',success=False))

    def test_package_masks_and_version_override(self):
        self.put('Directory.Packages.props','<Project><PropertyGroup><ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally></PropertyGroup><ItemGroup><PackageVersion Include="Example" Version="2.0.0"/></ItemGroup></Project>')
        self.put('Core/Core.csproj','<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><PackageReference Include="Example" VersionOverride="1.0.0" PrivateAssets="compile" IncludeAssets="compile;runtime" ExcludeAssets="build"/></ItemGroup></Project>')
        self.put('sync.json',json.dumps(dict(packages={'Example/1.0.0':dict(label=':example',roles=['deps'])})))
        self.run_sync('Core/Core.csproj','--mappings','sync.json')
        self.assertIn('"Example":"compile"',(self.root/'projects.generated.bzl').read_text())
        self.put('Directory.Packages.props','<Project><PropertyGroup><ManagePackageVersionsCentrally>true</ManagePackageVersionsCentrally><CentralPackageVersionOverrideEnabled>false</CentralPackageVersionOverrideEnabled></PropertyGroup></Project>')
        self.assertIn('overrides are disabled',self.run_sync('Core/Core.csproj','--mappings','sync.json',success=False))
