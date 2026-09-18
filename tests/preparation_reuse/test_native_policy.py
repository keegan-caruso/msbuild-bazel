"""Fail-closed boundaries added for the pinned native approval-test plan."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from discovery_contract import check_xml, TEST_PACKAGES
from preparation_reuse import prepared_view
from preparation_identity import IdentityError


class NativePolicyTests(unittest.TestCase):
    def test_only_reviewed_runtime_option_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'project.targets'
            option = '<RuntimeHostConfigurationOption Condition="\'$(PublishTrimmed)\' == \'true\'" Include="Serilog.Capturing.IsStructureValueSupported" Value="false" Trim="true" />'
            path.write_text('<Project><ItemGroup>' + option + '</ItemGroup></Project>')
            check_xml(path)
            for changed in (option.replace('Value="false"', 'Value="true"'), option.replace('IsStructureValueSupported', 'Other'), option.replace('Trim="true"', 'Trim="false"')):
                path.write_text('<Project><ItemGroup>' + changed + '</ItemGroup></Project>')
                with self.assertRaises(IdentityError): check_xml(path)

    def test_optional_source_path_switch_does_not_change_synthetic_requirements(self):
        from discovery_contract import SDK_SWITCHES
        self.assertNotIn('DeterministicSourcePaths', SDK_SWITCHES)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'project.csproj'
            for value in ('false', 'true', '$(Value)'):
                path.write_text('<Project><PropertyGroup><DeterministicSourcePaths>' + value + '</DeterministicSourcePaths></PropertyGroup></Project>')
                if value == 'false': check_xml(path)
                else:
                    with self.assertRaises(IdentityError): check_xml(path)

    def test_test_packages_have_archive_pins_and_imports_are_package_bound(self):
        policy = json.loads((Path(__file__).resolve().parents[2] / 'tools/pilot-package-policy.json').read_text())
        self.assertTrue(set(TEST_PACKAGES['packages']).issubset(policy))
        for path, value in TEST_PACKAGES['imports'].items():
            self.assertIn('/'.join(path.split('/')[:2]), TEST_PACKAGES['packages'])
            self.assertRegex(value, '^[a-f0-9]{64}$')

    def test_invalid_native_request_rejects_before_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); source = root / 'src'; source.mkdir()
            for options in ({'native_toolchain': 'bad'}, {'native_toolchain': 'a' * 64, 'tests': []},
                            {'native_toolchain': 'a' * 64, 'compile_boundary': True}):
                with self.assertRaises(IdentityError):
                    with prepared_view(source, root / 'state', root / 'output', [], **options): pass
                self.assertFalse((root / 'state').exists())
                self.assertFalse((root / 'output').exists())
