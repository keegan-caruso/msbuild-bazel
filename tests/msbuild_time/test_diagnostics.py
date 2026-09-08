import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('check_msbuild_time', Path(__file__).resolve().parents[2] / 'tools/check_msbuild_time.py')
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class TimeDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def scan(self, xml):
        path = self.root / 'Build.proj'
        path.write_text(xml)
        return CHECK.scan([path])

    def test_conditional_clock_retains_context(self):
        report = self.scan('''<Project><PropertyGroup Condition="'$(OfficialBuildId)' == ''">
<Version>$([System.DateTime]::Now.ToString(yyyyMMdd)).1</Version></PropertyGroup></Project>''')
        finding, = report['findings']
        self.assertEqual((finding['rule'], finding['line'], finding['phase']), ('wall-clock', 2, 'evaluation'))
        self.assertEqual(finding['conditions'], ["'$(OfficialBuildId)' == ''"])
        self.assertEqual(report['eligibility'], 'not-established')

    def test_timestamp_conditions_and_item_metadata(self):
        report = self.scan('''<Project><Target Name="Generate" Condition="$([System.IO.File]::GetLastWriteTimeUtc('input')) != ''">
<Message Text="%(Compile.ModifiedTime)" /></Target></Project>''')
        self.assertEqual([f['rule'] for f in report['findings']], ['file-timestamp', 'item-timestamp'])
        self.assertTrue(all(f['target'] == 'Generate' for f in report['findings']))

    def test_literal_imports_and_cycle(self):
        (self.root / 'Version.props').write_text('<Project><Import Project="Build.proj"/><PropertyGroup><V>$([System.DateTimeOffset]::UtcNow)</V></PropertyGroup></Project>')
        report = self.scan('<Project><Import Project="$(MSBuildThisFileDirectory)Version.props" /></Project>')
        self.assertEqual(len(report['files']), 2)
        self.assertEqual(len(report['findings']), 1)

    def test_application_clock_is_not_scanned(self):
        (self.root / 'Program.cs').write_text('System.Console.WriteLine(System.DateTime.Now);')
        report = self.scan('<Project><ItemGroup><Compile Include="Program.cs" /></ItemGroup></Project>')
        self.assertEqual(report['findings'], [])
        self.assertFalse(report['reuseEnabled'])

    def test_comments_and_explicit_input_are_not_clock_reads(self):
        report = self.scan('<Project><!-- $([System.DateTime]::Now) --><PropertyGroup><Version>$(OfficialBuildId)</Version></PropertyGroup></Project>')
        self.assertEqual(report['findings'], [])

    def test_escaping_and_namespace(self):
        report = self.scan('<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003"><PropertyGroup><V>%24([System.DateTime]::Today)</V></PropertyGroup></Project>')
        self.assertEqual(report['findings'][0]['rule'], 'wall-clock')

    def test_unresolved_imports_and_external_code_are_explicit(self):
        report = self.scan('<Project Sdk="Microsoft.NET.Sdk"><Import Project="$(Other)/a.props"/><Import Project="Absent.props"/><UsingTask TaskName="T" AssemblyFile="task.dll"/><Target Name="Build"><Exec Command="date"/></Target></Project>')
        self.assertEqual(len(report['coverageGaps']), 5)
        self.assertEqual(report['eligibility'], 'not-established')

    def test_false_import_condition_does_not_hide_potential_read(self):
        (self.root / 'Unused.props').write_text('<Project><PropertyGroup><V>$([System.DateTime]::Now)</V></PropertyGroup></Project>')
        report = self.scan('<Project><Import Project="Unused.props" Condition="false"/></Project>')
        self.assertEqual(len(report['findings']), 1)
        self.assertEqual(report['imports'][0]['conditions'], ['false'])

    def test_invalid_xml_is_error(self):
        self.assertTrue(self.scan('<Project>')['errors'])

    def test_dtd_is_rejected(self):
        self.assertTrue(self.scan('<!DOCTYPE Project [<!ENTITY clock "x">]><Project/>')['errors'])

    def test_source_file_as_entry_is_rejected(self):
        self.assertTrue(CHECK.scan([self.root / 'Program.cs'])['errors'])

    def test_clock_and_timestamp_variants(self):
        for expression, rule in [('$([System.Environment]::TickCount64)', 'elapsed-clock'),
                                 ('$([System.Diagnostics.Stopwatch]::GetTimestamp())', 'elapsed-clock'),
                                 ('$([System.IO.Directory]::GetCreationTime("."))', 'file-timestamp'),
                                 ('%(AccessedTime)', 'item-timestamp')]:
            with self.subTest(expression=expression):
                self.assertEqual(self.scan('<Project><PropertyGroup><V>' + expression + '</V></PropertyGroup></Project>')['findings'][0]['rule'], rule)


if __name__ == '__main__':
    unittest.main()
