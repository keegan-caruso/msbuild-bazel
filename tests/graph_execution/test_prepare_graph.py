"""Fail-closed preparation scope checks; no compiler or Bazel required."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_graph import prepare

class PreparationRejection(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.workspace = self.root / 'source'
        (self.workspace / 'App/obj').mkdir(parents=True)
        self.assets = {'libraries': {}, 'targets': {'net10.0': {}},
                       'project': {'frameworks': {'net10.0': {}}}}
        (self.workspace / 'App/obj/project.assets.json').write_text(json.dumps(self.assets))
        (self.workspace / 'App/App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"/>')
        self.node = dict(id='a' * 24, project='workspace/App/App.csproj', globalProperties={'configuration': 'Release'}, targetFramework='net10.0', outputType='Exe', dependencies=[], inputs=[dict(kind='project', path='workspace/App/App.csproj', sha256=hashlib.sha256((self.workspace / 'App/App.csproj').read_bytes()).hexdigest())], outputs=[dict(kind='assembly', path='workspace/App/bin/Release/net10.0/App.dll')])
        self.graph = dict(schemaVersion=1, toolchain=dict(sdkVersion='10.0.400', graphEngine='ProjectGraph', contractVersion=1), entryPoints=['a'*24], graphInputs=[], nodes=[self.node])

    def tearDown(self):
        self.temporary.cleanup()

    def rejected(self, message):
        manifest = self.root / 'graph.json'
        manifest.write_text(json.dumps(self.graph))
        with self.assertRaisesRegex(ValueError, message):
            prepare(self.workspace, manifest, self.root / 'generated')
        self.assertFalse((self.root / 'generated').exists())

    def test_leased_preparation_rejects_unqualified_toolchain_overrides(self):
        from prepare_graph import _prepare
        for options in ({'sdk_version': '11.0.100-test'}, {'sdk_root': self.root},
                        {'tool_framework': 'net11.0'}, {'engine_root': self.root}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, 'qualified default toolchain'):
                _prepare(self.workspace, self.root / 'absent.json', self.root / 'generated', _leased=True, **options)
        self.assertFalse((self.root / 'generated').exists())

    def test_selected_sdk_must_match_discovery(self):
        manifest = self.root / 'graph.json'
        manifest.write_text(json.dumps(self.graph))
        with self.assertRaisesRegex(ValueError, 'unsupported graph schema'):
            prepare(self.workspace, manifest, self.root / 'generated', sdk_version='11.0.100-test')
        self.assertFalse((self.root / 'generated').exists())

    def test_matching_alternate_sdk_passes_schema_validation(self):
        self.graph['toolchain']['sdkVersion'] = '11.0.100-test'
        manifest = self.root / 'graph.json'
        manifest.write_text(json.dumps(self.graph))
        with self.assertRaisesRegex(ValueError, 'graph discovery request missing'):
            prepare(self.workspace, manifest, self.root / 'generated', sdk_version='11.0.100-test')
        self.assertFalse((self.root / 'generated').exists())

    def test_same_path_configured_output_collision_rejected(self):
        self.node['execution'] = dict(assetsFile='workspace/App/obj/project.assets.json',
            outputDirectory='workspace/App/bin/Release/net10.0', referenceDirectory='workspace/App/obj/Release/net10.0/ref')
        other = json.loads(json.dumps(self.node))
        other['id'] = 'b' * 24
        other['globalProperties']['flavor'] = 'blue'
        self.node['globalProperties']['flavor'] = 'red'
        self.graph['nodes'].append(other)
        self.rejected('configured-output-collision')

    def test_configured_restore_path_escape_rejected(self):
        self.node['execution'] = dict(assetsFile='workspace/App/../other/project.assets.json',
            outputDirectory='workspace/App/bin/red/Release/net10.0', referenceDirectory='workspace/App/obj/red/Release/net10.0/ref')
        self.rejected('unsafe workspace path')

    def test_import_hash_preserves_crlf_and_decodes_bom(self):
        source = self.workspace / 'Imported.targets'
        text = '<Project>\r\n<!-- ' + str(self.workspace.resolve()) + '/value -->\r\n</Project>\r\n'
        expected = text.replace(str(self.workspace.resolve()), '$WORKSPACE').encode('utf-8')
        record = dict(kind='import', path='workspace/Imported.targets', sha256=hashlib.sha256(expected).hexdigest())
        self.node['inputs'].append(record)
        for encoding in ('utf-8', 'utf-8-sig', 'utf-16', 'utf-32'):
            with self.subTest(encoding=encoding):
                source.write_bytes(text.encode(encoding))
                self.rejected('graph discovery request missing')
        for encoding, marker in (('utf-16-be', b'\xfe\xff'), ('utf-32-be', b'\x00\x00\xfe\xff')):
            with self.subTest(encoding=encoding):
                source.write_bytes(marker + text.encode(encoding))
                self.rejected('graph discovery request missing')

    def test_unsupported_global_property(self):
        self.node['globalProperties']['defineconstants'] = 'OTHER'
        self.rejected('configuration')

    def test_unsupported_versioning_modes_rejected_before_publication(self):
        for key, value in (('nbgv_cachemode', 'MSBuildTargetCaching'),
                           ('nbgv_cachemode', 'None;PublicRelease=true'),
                           ('publicrelease', 'auto')):
            with self.subTest(key=key, value=value):
                self.node['globalProperties'] = {'configuration': 'Release', key: value}
                self.rejected('unsupported graph versioning configuration')

    def test_debug_rejected(self):
        self.node['globalProperties']['configuration'] = 'Debug'
        self.rejected('configuration')

    def test_nonstandard_output_layout(self):
        self.node['outputs'][0]['path'] = 'workspace/custom/App.dll'
        self.rejected('output layout')

    def test_incomplete_package_restore_rejected(self):
        self.assets['libraries']['Example/1.0.0'] = {'type': 'package'}
        self.assets['targets']['net10.0']['Example/1.0.0'] = {'type': 'package'}
        (self.workspace / 'App/obj/project.assets.json').write_text(json.dumps(self.assets))
        self.rejected('unsupported-package: incomplete restored package metadata')

    def test_stale_source_manifest(self):
        (self.workspace / 'App/App.csproj').write_text('changed')
        self.rejected('stale graph input')

    def test_stale_import_manifest(self):
        source = self.workspace / 'Directory.Build.props'
        source.write_text('<Project/>')
        self.node['inputs'].append(dict(kind='import', path='workspace/Directory.Build.props', sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
        source.write_text('<Project><PropertyGroup><OutputPath>other</OutputPath></PropertyGroup></Project>')
        self.rejected('stale graph input')

    def test_stale_restore_manifest(self):
        source = self.workspace / 'App/obj/project.assets.json'
        self.node['inputs'].append(dict(kind='restore', path='workspace/App/obj/project.assets.json', sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
        source.write_text(json.dumps(self.assets, indent=2))
        self.rejected('stale graph input')

    def test_stale_traversal_input(self):
        source = self.workspace / 'build.proj'
        source.write_text('<Project/>')
        self.graph['graphInputs'].append(dict(kind='project', path='workspace/build.proj', sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
        source.write_text('changed')
        self.rejected('stale graph input')

    def test_declared_obj_source_rejected(self):
        source = self.workspace / 'App/obj/Generated.cs'
        source.write_text('class Generated {}')
        self.node['inputs'].append(dict(kind='source', path='workspace/App/obj/Generated.cs', sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
        self.rejected('unsupported declared obj input')

    def test_missing_input(self):
        (self.workspace / 'App/App.csproj').unlink()
        self.rejected('missing or escaping input')

    def test_symlink_escape(self):
        outside = self.root / 'outside.csproj'
        outside.write_text('<Project/>')
        (self.workspace / 'App/App.csproj').unlink()
        (self.workspace / 'App/App.csproj').symlink_to(outside)
        self.rejected('missing or escaping input')

    def test_missing_discovery_request_rejected(self):
        self.rejected('graph discovery request missing')

    def test_missing_dependency(self):
        self.node['dependencies'] = ['b'*24]
        self.rejected('missing dependency')

    def test_cycle(self):
        self.node['dependencies'] = ['a'*24]
        self.rejected('cyclic graph')

if __name__ == '__main__':
    unittest.main()
