"""Graph snapshot diagnostics verify bytes and retain their eligibility limits."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from msbuild_graph_diagnostics import scan_graph


class GraphDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.workspace = self.root / 'work'
        self.workspace.mkdir()
        self.project = self.workspace / 'App.csproj'
        self.project.write_text('<Project><Import Project="inactive.props" Condition="false" /></Project>')
        (self.workspace / 'inactive.props').write_text('<Project><PropertyGroup><V>$([System.DateTime]::Now)</V></PropertyGroup></Project>')
        self.props = self.workspace / 'selected.props'
        self.props.write_text('<Project><Target Name="Observe"><Message Text="%(Compile.ModifiedTime)" /></Target></Project>')
        self.entries = [dict(project='App.csproj', globalProperties={'Configuration': 'Release'})]
        inputs = [dict(kind=kind, path='workspace/' + path.name,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest()) for kind, path in [('project', self.project), ('import', self.props)]]
        self.graph = dict(schemaVersion=1, toolchain=dict(sdkVersion='10.0.400'), graphInputs=[],
            entryRequests=self.entries, nodes=[dict(id='app', project='workspace/App.csproj', globalProperties={'configuration': 'Release'}, inputs=inputs)])
        self.request = dict(schemaVersion=1, sdkVersion='10.0.400', workspace=str(self.workspace),
            dotnetRoot=str(self.root / 'dotnet'), packageRoot=str(self.workspace / '.nuget/packages'),
            output=str(self.root / 'graph.json'), entryPoints=self.entries)

    def run_scan(self):
        (self.root / 'graph.json').write_text(json.dumps(self.graph))
        path = self.root / 'request.json'
        path.write_text(json.dumps(self.request))
        return scan_graph(path)

    def test_scans_only_recorded_xml_and_attributes_owners(self):
        report = self.run_scan()
        self.assertEqual(report['errors'], [])
        self.assertTrue(report['inventoryVerified'])
        self.assertEqual([f['rule'] for f in report['findings']], ['item-timestamp'])
        self.assertEqual(report['findings'][0]['configuredNodes'], ['app'])
        self.assertFalse(report['reuseEnabled'])
        self.assertEqual(report['eligibility'], 'not-established')
        self.assertTrue(any('snapshot membership' in g['reason'] for g in report['coverageGaps']))

    def test_stale_or_missing_import_rejected_before_scanning(self):
        self.props.write_text('<Project />')
        self.assertIn('stale graph XML', self.run_scan()['errors'][0]['message'])
        self.props.unlink()
        self.assertIn('missing or escaping', self.run_scan()['errors'][0]['message'])

    def test_normalized_utf16_import_hash(self):
        value = '<Project><PropertyGroup><P>' + str(self.workspace) + '</P></PropertyGroup></Project>\r\n'
        self.props.write_bytes(value.encode('utf-16'))
        self.graph['nodes'][0]['inputs'][1]['sha256'] = hashlib.sha256(value.replace(str(self.workspace), '$WORKSPACE').encode()).hexdigest()
        self.assertEqual(self.run_scan()['errors'], [])

    def test_configuration_mismatch_rejected(self):
        self.request['entryPoints'] = [dict(project='App.csproj', globalProperties={'Configuration': 'Debug'})]
        self.assertIn('configuration mismatch', self.run_scan()['errors'][0]['message'])

    def test_escaping_and_unmapped_paths_rejected(self):
        for path in ('workspace/../outside.props', '/outside.props', 'host/outside.props', 'workspace//selected.props'):
            with self.subTest(path=path):
                self.graph['nodes'][0]['inputs'][1]['path'] = path
                self.assertIn('unsafe graph XML', self.run_scan()['errors'][0]['message'])

    def test_workspace_symlink_escape_rejected(self):
        self.props.unlink()
        outside = self.root / 'outside.props'
        outside.write_text('<Project/>')
        self.props.symlink_to(outside)
        self.assertIn('missing or escaping', self.run_scan()['errors'][0]['message'])

    def test_conflicting_hash_records_rejected(self):
        self.graph['graphInputs'] = [dict(self.graph['nodes'][0]['inputs'][1], sha256='0' * 64)]
        self.assertIn('conflicting', self.run_scan()['errors'][0]['message'])

    def test_parser_uses_verified_bytes_not_a_second_file_read(self):
        from msbuild_graph_diagnostics import scan
        def after_verification(*args, **kwargs):
            self.props.write_text('<Project><PropertyGroup><V>$([System.DateTime]::Now)</V></PropertyGroup></Project>')
            return scan(*args, **kwargs)
        with patch('msbuild_graph_diagnostics.scan', side_effect=after_verification):
            report = self.run_scan()
        self.assertEqual([f['rule'] for f in report['findings']], ['item-timestamp'])

    def test_package_and_nonstandard_xml_import_extensions(self):
        folder = Path(self.request['packageRoot'])
        folder.mkdir(parents=True)
        path = folder / 'version.inc'
        raw = b'<Project><PropertyGroup><V>$([System.DateTime]::Today)</V></PropertyGroup></Project>'
        path.write_bytes(raw)
        self.graph['nodes'][0]['inputs'].append(dict(kind='import', path='packages/version.inc', sha256=hashlib.sha256(raw).hexdigest()))
        report = self.run_scan()
        self.assertEqual(report['errors'], [])
        self.assertIn('wall-clock', [f['rule'] for f in report['findings']])

    def test_schema_and_sdk_mismatch_rejected(self):
        self.graph['schemaVersion'] = 2
        self.assertIn('unsupported', self.run_scan()['errors'][0]['message'])
        self.graph['schemaVersion'] = 1
        self.request['sdkVersion'] = 'other'
        self.assertIn('SDK mismatch', self.run_scan()['errors'][0]['message'])
