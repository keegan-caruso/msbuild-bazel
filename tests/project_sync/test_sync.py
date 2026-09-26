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

    def test_framework_mapping_overrides_are_explicit_and_validated(self):
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework/><TargetFrameworks>net9.0;net10.0</TargetFrameworks></PropertyGroup><ItemGroup Condition="\'$(Flavor)\' == \'modern\'"><Compile Remove="Core.cs"/></ItemGroup></Project>')
        mapping = dict(projectDefaults=dict(properties={'Common': 'yes'}), projects={'Core/Core.csproj': dict(frameworkOverrides={'net10.0': dict(properties={'Flavor': 'modern'}, generatedDirectories={'Core/Generated': 'data'})})})
        self.put('sync.json', json.dumps(mapping))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        output = (self.root / 'projects.generated.bzl').read_text()
        self.assertEqual(output.count('Core/Core.cs'), 2)  # project path and net9 source
        self.assertIn('"Flavor":"modern"', output)
        self.assertIn('"Common":"yes"', output)
        self.assertIn('"generated_directories": {"Core/Generated":"data"}', output)
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', '--check')
        for override, error in [
            ({'net8.0': {}}, 'selected frameworks'),
            ({'net10.0': {'targetFrameworks': ['net10.0']}}, 'cannot select or nest'),
            ({'net10.0': {'frameworkOverrides': {}}}, 'cannot select or nest'),
            ({'net10.0': {'properties': {'Configuration': 'Debug'}}}, 'reserved evaluation property'),
            ({'net10.0': {'unknownField': True}}, 'could not be mapped'),
        ]:
            mapping['projects']['Core/Core.csproj']['frameworkOverrides'] = override
            self.put('sync.json', json.dumps(mapping))
            self.assertIn(error, self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))
            self.assertEqual(output, (self.root / 'projects.generated.bzl').read_text())

    def test_shared_imports_keep_project_globals_and_refresh_between_runs(self):
        import ast
        self.put('Shared.props', """<Project><ItemGroup><Compile Remove="*.cs"/><Compile Include="$(Flavor).cs"/></ItemGroup></Project>""")
        for name in ['Core', 'Other']:
            self.put(name + '/' + name + '.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><EnableDefaultCompileItems>false</EnableDefaultCompileItems></PropertyGroup></Project>')
            for flavor in ['First', 'Second']:
                self.put(name + '/' + flavor + '.cs', 'class ' + flavor + ' {}')
        mapping = dict(projects={name + '/' + name + '.csproj': dict(properties={'Flavor': flavor}) for name, flavor in [('Core', 'First'), ('Other', 'Second')]})
        self.put('sync.json', json.dumps(mapping))
        args = ['Core/Core.csproj', 'Other/Other.csproj', '--mappings', 'sync.json']
        self.run_sync(*args)
        def sources():
            calls = [node for node in ast.walk(ast.parse((self.root / 'projects.generated.bzl').read_text())) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'msbuild_project']
            return {attrs['project']: attrs['framework_overrides']['net10.0']['srcs'] for node in calls for attrs in [{k.arg: ast.literal_eval(k.value) for k in node.keywords}]}
        self.assertEqual(sources(), {'Core/Core.csproj': ['Core/First.cs'], 'Other/Other.csproj': ['Other/Second.cs']})
        self.put('Shared.props', '<Project><ItemGroup><Compile Include="Second.cs"/></ItemGroup></Project>')
        self.assertIn('stale', self.run_sync(*args, '--check', success=False))
        self.run_sync(*args)
        self.assertEqual(sources(), {'Core/Core.csproj': ['Core/Second.cs'], 'Other/Other.csproj': ['Other/Second.cs']})

    def test_starlark_strings_preserve_unicode_quotes_and_literal_escapes(self):
        import ast
        self.put('Core/é中😀.cs', 'class UnicodeFile {}')
        value = "é中😀 <tag> a+b & quoted \"value\" \\u1234\n\t"
        self.put('sync.json', json.dumps(dict(projects={'Core/Core.csproj':dict(properties={'LiteralProbe':value})})))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        text = (self.root/'projects.generated.bzl').read_text()
        calls = [node for node in ast.walk(ast.parse(text)) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'msbuild_project']
        attrs = {k.arg:ast.literal_eval(k.value) for k in calls[0].keywords}
        self.assertEqual(attrs['msbuild_properties']['LiteralProbe'], value)
        self.assertIn('Core/é中😀.cs', attrs['framework_overrides']['net10.0']['srcs'])

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
            ({'Core/Core.csproj':dict(properties={'Flavor':'a', 'flavor':'b'})}, 'Ambiguous'),
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
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><Compile Include="../Shared/Shared.cs" Link="Shared/Shared.cs" SubType="Code"/><EmbeddedResource Include="message.txt" LogicalName="Probe.Message" Language="CSharp" SubType="Designer"/><AdditionalFiles Include="options.txt"/><None Update="options.txt" CopyToOutputDirectory="PreserveNewest"/></ItemGroup></Project>')
        self.run_sync('Core/Core.csproj')
        output = (self.root/'projects.generated.bzl').read_text()
        for fragment in ['item_type = "Compile"', '"Link":"Shared/Shared.cs"', '"SubType":"Code"', 'item_type = "EmbeddedResource"', '"LogicalName":"Probe.Message"', '"Language":"CSharp"', '"SubType":"Designer"', 'item_type = "AdditionalFiles"', '"CopyToOutputDirectory":"PreserveNewest"']:
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

    def test_resource_item_order_matches_evaluation(self):
        import ast
        self.put('Core/z.txt', 'last alphabetically')
        self.put('Core/a.txt', 'first alphabetically')
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><EmbeddedResource Include="z.txt;a.txt"/></ItemGroup></Project>')
        self.run_sync('Core/Core.csproj')
        tree = ast.parse((self.root/'projects.generated.bzl').read_text())
        items = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id == 'msbuild_items':
                row = {k.arg:ast.literal_eval(k.value) for k in node.keywords}
                if row['item_type'] == 'EmbeddedResource':
                    items[':'+row['name']] = row['srcs']
            if node.func.id == 'msbuild_project':
                project = {k.arg:ast.literal_eval(k.value) for k in node.keywords}
        labels = project['framework_overrides']['net10.0']['items']
        self.assertEqual([path for label in labels if label in items for path in items[label]], ['Core/z.txt', 'Core/a.txt'])
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

    def test_web_and_razor_framework_inputs(self):
        for sdk, output in [('Microsoft.NET.Sdk.Web', '<OutputType>Exe</OutputType>'), ('Microsoft.NET.Sdk.Razor', '')]:
            self.put('Core/Core.csproj', '<Project Sdk="' + sdk + '"><PropertyGroup>' + output + '</PropertyGroup><ItemGroup><FrameworkReference Include="Microsoft.AspNetCore.App"/></ItemGroup></Project>')
            self.run_sync('Core/Core.csproj')
            generated = (self.root/'projects.generated.bzl').read_text()
            self.assertIn('framework_refs', generated)
            self.assertIn('Microsoft.AspNetCore.App', generated)
            self.run_sync('Core/Core.csproj', '--check')
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><FrameworkReference Include="Microsoft.AspNetCore.App" PrivateAssets="all"/></ItemGroup></Project>')
        self.assertIn('FrameworkReference metadata', self.run_sync('Core/Core.csproj', success=False))

    def test_apphost_override_uses_the_rule_attribute(self):
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup></Project>')
        self.put('sync.json', json.dumps(dict(projects={'Core/Core.csproj':dict(useAppHost=False)})))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        generated = (self.root/'projects.generated.bzl').read_text()
        self.assertIn('use_apphost = False', generated)
        self.assertNotIn('"UseAppHost"', generated)
        self.put('sync.json', json.dumps(dict(projects={'Core/Core.csproj':dict(properties={'UseAppHost':'false'})})))
        self.assertIn('reserved', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))

    def test_implicit_frameworks_are_not_transitive(self):
        for framework in ['net10.0', 'netstandard2.1']:
            self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>' + framework + '</TargetFramework></PropertyGroup></Project>')
            self.run_sync('Core/Core.csproj')
            self.assertNotIn('framework_refs', (self.root/'projects.generated.bzl').read_text())

    def test_explicit_file_item_types_and_metadata(self):
        self.put('Core/input.xml', '<interface/>')
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><ProtocolInput Include="input.xml" Mode="client"/></ItemGroup></Project>')
        self.assertIn('ProtocolInput', self.run_sync('Core/Core.csproj', success=False))
        mapping = dict(projects={'Core/Core.csproj': dict(inputItems={'ProtocolInput': ['Mode']})})
        self.put('sync.json', json.dumps(mapping))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        output = (self.root/'projects.generated.bzl').read_text()
        for value in ['item_type = "ProtocolInput"', 'Core/input.xml', '"Mode":"client"']:
            self.assertIn(value, output)
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', '--check')
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><ProtocolInput Include="input.xml" Mode="/outside"/></ItemGroup></Project>')
        self.assertIn('Unsafe item metadata', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))
        self.assertEqual(output, (self.root/'projects.generated.bzl').read_text())
        mapping['projects']['Core/Core.csproj']['inputItems'] = {'ProjectReference': []}
        self.put('sync.json', json.dumps(mapping))
        self.assertIn('dependency/source mappings', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))

    def test_target_exports_require_existing_reviewed_target(self):
        project = '<Project Sdk="Microsoft.NET.Sdk"><Target Name="Describe" Returns="@(Description)"><ItemGroup><Description Include="Core"/></ItemGroup></Target></Project>'
        self.put('Core/Core.csproj', project)
        contract = dict(sha256=hashlib.sha256(project.encode()).hexdigest(), targets=['Describe'], tasks=[])
        binding = dict(exportTargets={'Describe': []}, documents={'Core/Core.csproj': contract})
        self.put('sync.json', json.dumps(dict(projects={'Core/Core.csproj': binding})))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        output = (self.root/'projects.generated.bzl').read_text()
        self.assertIn('"export_targets": {"Describe":[]}', output)
        binding['exportTargets'] = {'Missing': []}
        self.put('sync.json', json.dumps(dict(projects={'Core/Core.csproj': binding})))
        self.assertIn('Export target is not declared', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))
        self.assertEqual(output, (self.root/'projects.generated.bzl').read_text())

    def test_project_defaults_preserve_flat_graph_and_explicit_precedence(self):
        self.put('App/App.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><ProjectReference Include="../Core/Core.csproj"/></ItemGroup></Project>')
        defaults = dict(platform='AnyCPU', properties={'Flavor': 'base', 'Common': 'yes'}, adapterImports=[':adapter'], evaluationItems=['Bookkeeping'], transitiveCompileReferences=False)
        core = dict(defaults, platform='arm64', properties={'Flavor': 'special', 'Common': 'yes'}, adapterImports=[], transitiveCompileReferences=True)
        self.put('sync.json', json.dumps(dict(projects={'App/App.csproj': defaults, 'Core/Core.csproj': core})))
        self.run_sync('App/App.csproj', '--mappings', 'sync.json')
        output = (self.root/'projects.generated.bzl').read_bytes()
        # Unlisted reachable projects also receive defaults; explicit empty lists
        # and booleans override inherited values rather than being appended.
        self.put('sync.json', json.dumps(dict(projectDefaults=defaults, projects={'Core/Core.csproj': dict(platform='arm64', properties={'Flavor': 'special'}, adapterImports=[], transitiveCompileReferences=True)})))
        self.run_sync('App/App.csproj', '--mappings', 'sync.json', '--check')
        self.assertEqual(output, (self.root/'projects.generated.bzl').read_bytes())
        self.run_sync('App/App.csproj', '--mappings', 'sync.json')
        self.assertEqual(output, (self.root/'projects.generated.bzl').read_bytes())

    def test_default_document_contracts_remain_reviewed_and_stale_checked(self):
        logic = '<Project><Target Name="Reviewed"/></Project>'
        self.put('Core/Logic.targets', logic)
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><Import Project="Logic.targets"/></Project>')
        contract = dict(sha256=hashlib.sha256(logic.encode()).hexdigest(), targets=['Reviewed'], tasks=[])
        mapping = dict(projectDefaults=dict(documents={'Core/Logic.targets': contract}))
        self.put('sync.json', json.dumps(mapping))
        self.run_sync('Core/Core.csproj', '--mappings', 'sync.json')
        output = (self.root/'projects.generated.bzl').read_bytes()
        mapping['projects'] = {'Core/Core.csproj': dict(documents={'Core/Logic.targets': dict(targets=['Reviewed'])})}
        self.put('sync.json', json.dumps(mapping))
        self.assertIn('contract changed', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))
        self.assertEqual(output, (self.root/'projects.generated.bzl').read_bytes())
        del mapping['projects']
        self.put('sync.json', json.dumps(mapping))
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"/>')
        self.assertIn('does not match evaluated imports', self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))
        self.assertEqual(output, (self.root/'projects.generated.bzl').read_bytes())

    def test_ambiguous_defaults_and_unsafe_values_fail_without_replacing_output(self):
        self.run_sync('Core/Core.csproj')
        output = (self.root/'projects.generated.bzl').read_bytes()
        cases = [
            ('{"projectDefaults":{"platform":"arm64","platform":"AnyCPU"}}', 'Duplicate mapping key'),
            ('{"projectDefaults":{"platform":"arm64","Platform":"AnyCPU"}}', 'Ambiguous mapping member'),
            ('{"projectDefaults":null}', 'must be an object'),
            ('{"projectDefaults":{"properties":{"Flavor":"one","flavor":"two"}}}', 'Ambiguous mapping member'),
            ('{"projectDefaults":{"packageReferencePaths":{"Example":["../outside.dll"]}}}', 'safe relative'),
            ('{"projectDefaults":{"bindings":["ambient-tool"]}}', 'explicit Bazel label'),
            ('{"projectDefaults":{"unknown":true}}', 'could not be mapped'),
        ]
        for text, diagnostic in cases:
            self.put('sync.json', text)
            self.assertIn(diagnostic, self.run_sync('Core/Core.csproj', '--mappings', 'sync.json', success=False))
            self.assertEqual(output, (self.root/'projects.generated.bzl').read_bytes())

    def test_failure_names_project_configuration_item_and_mapping(self):
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><CustomInput Include="input.txt"/></ItemGroup></Project>')
        diagnostic = self.run_sync('Core/Core.csproj', success=False)
        for fragment in ['Core/Core.csproj', 'Configuration=Release', 'Platform=AnyCPU', 'TargetFramework=net10.0', 'CustomInput', 'input.txt', 'evaluationItems']:
            self.assertIn(fragment, diagnostic)
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><Target Name="Generate"/></Project>')
        diagnostic = self.run_sync('Core/Core.csproj', success=False)
        for fragment in ['Core/Core.csproj', 'TargetFramework=net10.0', 'documents[', 'sha256']:
            self.assertIn(fragment, diagnostic)

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

    def test_project_package_mapping_overrides_shared_closure(self):
        self.put('Core/Core.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><PackageReference Include="Example" Version="1.0.0"/></ItemGroup></Project>')
        self.put('App/App.csproj', '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><ProjectReference Include="../Core/Core.csproj"/><PackageReference Include="Example" Version="1.0.0"/></ItemGroup></Project>')
        mapping = dict(packages={'Example/1.0.0':dict(label=':shared', roles=['deps'])}, projects={'Core/Core.csproj':dict(packages={'Example/1.0.0':dict(label=':specific', roles=['deps'])})})
        self.put('sync.json', json.dumps(mapping))
        self.run_sync('App/App.csproj', '--mappings', 'sync.json')
        output = (self.root/'projects.generated.bzl').read_text()
        self.assertEqual(output.count(':specific'), 1)
        self.assertEqual(output.count(':shared'), 1)
        mapping['projects']['Core/Core.csproj']['packages']['example/1.0.0'] = dict(label=':ambiguous',roles=['deps'])
        self.put('sync.json', json.dumps(mapping))
        self.assertIn('unique ID/version', self.run_sync('App/App.csproj', '--mappings', 'sync.json', success=False))
        self.assertEqual(output, (self.root/'projects.generated.bzl').read_text())

    def test_project_package_locks_scope_evaluation(self):
        for version in ['1', '2']:
            self.put('runfiles/v' + version + '/marker', version)
        self.put('App/App.csproj', """<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><ProjectReference Include="../Core/Core.csproj"/></ItemGroup><PropertyGroup><Nullable>disable</Nullable><Nullable Condition="Exists('../.nuget/packages/example/1/marker') and !Exists('../.nuget/packages/example/2/marker')">enable</Nullable></PropertyGroup></Project>""")
        self.put('App/App.cs', 'class App {}')
        self.put('Core/Core.csproj', """<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><Nullable Condition="Exists('../.nuget/packages/example/2/marker') and !Exists('../.nuget/packages/example/1/marker')">disable</Nullable></PropertyGroup></Project>""")
        manifest = dict(inputs=[], packages=[dict(id='Example', version=v, runfile='v' + v) for v in ['1', '2']], packageLock=':one', packageLocks=[dict(label=':one', packages=['example/1']), dict(label=':two', packages=['example/2'])])
        mapping = dict(projects={'Core/Core.csproj': dict(packageLock=':two')})
        self.put('inputs.json', json.dumps(manifest))
        self.put('sync.json', json.dumps(mapping))
        args = ['App/App.csproj', '--mappings', 'sync.json', '--inputs', str(self.root/'inputs.json'), '--runfiles', str(self.root/'runfiles')]
        self.run_sync(*args)
        output = (self.root/'projects.generated.bzl').read_text()
        import ast
        tree = ast.parse(output)
        declarations = [node for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'msbuild_project']
        rows = {ast.literal_eval(next(k.value for k in node.keywords if k.arg == 'name')): {k.arg: ast.literal_eval(k.value) for k in node.keywords} for node in declarations}
        self.assertEqual(rows['App_App']['framework_overrides']['net10.0']['nullable'], 'enable')
        self.assertEqual(rows['Core_Core']['framework_overrides']['net10.0']['nullable'], 'disable')
        self.assertEqual(rows['App_App']['framework_overrides']['net10.0']['package_lock'], ':one')
        self.assertEqual(rows['Core_Core']['framework_overrides']['net10.0']['package_lock'], ':two')
        self.run_sync(*args, '--check')
        mapping['projects']['Core/Core.csproj']['packageLock'] = ':missing'
        self.put('sync.json', json.dumps(mapping))
        self.assertIn('declared sync package lock', self.run_sync(*args, success=False))
        self.assertEqual(output, (self.root/'projects.generated.bzl').read_text())
        manifest['packageLocks'][0]['packages'].append('example/3')
        self.put('inputs.json', json.dumps(manifest))
        self.assertIn('conflicting sync package lock', self.run_sync(*args, success=False))
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
