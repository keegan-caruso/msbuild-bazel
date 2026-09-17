import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from discovery_contract import check_xml, seal, EPOCH, validate_certificate
from preparation_identity import IdentityError, tree_snapshot


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def xml(self, text, name='App.csproj'):
        path = self.root / name
        path.write_text(text)
        return path

    def test_nested_and_property_selected_imports_use_msbuild_syntax(self):
        check_xml(self.xml('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><BuildStamp>42</BuildStamp></PropertyGroup>'
            '<Import Project="$(MSBuildThisFileDirectory)$(BuildStamp)/*.props" Condition="Exists(\'optional.props\')"/>'
            '<ItemGroup><ProjectReference Include="Shared.csproj"/><Compile Include="**/*.cs"/></ItemGroup></Project>'))

    def test_unqualified_executable_constructs_reject(self):
        for body in ('<Target Name="Build"/>', '<UsingTask TaskName="X" AssemblyFile="x.dll"/>',
                     '<PropertyGroup><ProcessFrameworkReferencesDependsOn>X</ProcessFrameworkReferencesDependsOn></PropertyGroup>',
                     '<ItemGroup><ProjectReference Include="A.csproj"><AdditionalProperties>X=1</AdditionalProperties></ProjectReference></ItemGroup>'):
            with self.subTest(body=body), self.assertRaises(IdentityError):
                check_xml(self.xml('<Project>' + body + '</Project>'))

    def test_clock_read_bypass_and_escaped_expressions_reject(self):
        for value in ('$([System.DateTime]::UtcNow)', '$([System.IO.File]::ReadAllText(\'x\'))',
                      '%24([System.DateTime]::Now)', '@(Compile->\'%(ModifiedTime)\')',
                      '$(BuildStamp.ToString())'):
            with self.subTest(value=value), self.assertRaises(IdentityError):
                check_xml(self.xml('<Project><PropertyGroup><Value>' + value + '</Value></PropertyGroup></Project>'))

    def test_resolver_initial_targets_dtd_and_arbitrary_extension_reject(self):
        for text in ('<Project Sdk="Unqualified.Sdk"/>', '<Project InitialTargets="X"/>',
                     '<!DOCTYPE Project><Project/>', '<Project><Target Name="X"/></Project>'):
            with self.subTest(text=text), self.assertRaises(IdentityError):
                check_xml(self.xml(text, 'import.data'))

    def test_seal_normalizes_timestamps_and_only_relocates_restore_metadata(self):
        source = self.root / 'source'
        (source / 'obj').mkdir(parents=True)
        (source / 'App.csproj').write_text('<Project/>')
        (source / 'Code.cs').write_text('class Code { string Root = "' + str(source) + '"; }')
        (source / 'obj/project.assets.json').write_text('{"root":"' + str(source) + '"}')
        (source / 'obj/authored.props').write_text('<Project><PropertyGroup><Value>' + str(source) + '</Value></PropertyGroup></Project>')
        original = tree_snapshot(source)
        destination = self.root / 'staged'
        seal(source, destination)
        self.assertEqual(original, tree_snapshot(source))
        self.assertEqual((source / 'Code.cs').read_bytes(), (destination / 'Code.cs').read_bytes())
        self.assertEqual((source / 'obj/authored.props').read_bytes(), (destination / 'obj/authored.props').read_bytes())
        self.assertIn(str(destination), (destination / 'obj/project.assets.json').read_text())
        self.assertTrue(all(p.stat().st_mtime == EPOCH for p in destination.rglob('*')))

    def test_workspace_symlinks_and_nested_stage_reject(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'data').write_text('value')
        (source / 'link').symlink_to('data')
        with self.assertRaises(IdentityError): seal(source, self.root / 'stage')
        with self.assertRaises(IdentityError): seal(source, source / 'stage')

    def test_changed_source_during_copy_rejects(self):
        from unittest.mock import patch
        import shutil
        original_copy = shutil.copytree
        source = self.root / 'source'
        source.mkdir()
        (source / 'data').write_text('one')
        def changing_copy(*args, **kwargs):
            result = original_copy(*args, **kwargs)
            (source / 'data').write_text('two')
            return result
        with patch('discovery_contract.shutil.copytree', side_effect=changing_copy):
            with self.assertRaisesRegex(IdentityError, 'source changed while sealing'):
                seal(source, self.root / 'stage')

    def test_scale_sdk_switches_require_qualified_literal_values(self):
        from discovery_contract import SDK_SWITCHES
        for name, value in SDK_SWITCHES.items():
            check_xml(self.xml(f'<Project><PropertyGroup><{name}>{value}</{name}></PropertyGroup></Project>'))
            for other in ('$(Value)', 'true' if value == 'false' else 'false'):
                with self.subTest(name=name, value=other), self.assertRaises(IdentityError):
                    check_xml(self.xml(f'<Project><PropertyGroup><{name}>{other}</{name}></PropertyGroup></Project>'))

    def test_incomplete_certificates_reject(self):
        for value in ({}, {'schemaVersion':2}, {'schemaVersion':1,'policy':'unqualified'}):
            with self.subTest(value=value), self.assertRaises(IdentityError): validate_certificate(value)


if __name__ == '__main__':
    unittest.main()
