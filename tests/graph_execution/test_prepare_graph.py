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
        (self.workspace / 'App/obj/project.assets.json').write_text('{"libraries":{}}')
        (self.workspace / 'App/App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"/>')
        self.node = dict(id='a' * 24, project='workspace/App/App.csproj', globalProperties={'configuration': 'Release'}, targetFramework='net10.0', outputType='Exe', dependencies=[], inputs=[dict(kind='project', path='workspace/App/App.csproj', sha256=hashlib.sha256((self.workspace / 'App/App.csproj').read_bytes()).hexdigest())], outputs=[dict(kind='assembly', path='workspace/App/bin/Release/net10.0/App.dll')])
        self.graph = dict(schemaVersion=1, toolchain=dict(sdkVersion='10.0.100', graphEngine='ProjectGraph', contractVersion=1), entryPoints=['a'*24], graphInputs=[], nodes=[self.node])

    def tearDown(self):
        self.temporary.cleanup()

    def rejected(self, message):
        manifest = self.root / 'graph.json'
        manifest.write_text(json.dumps(self.graph))
        with self.assertRaisesRegex(ValueError, message):
            prepare(self.workspace, manifest, self.root / 'generated')
        self.assertFalse((self.root / 'generated').exists())

    def test_unsupported_global_property(self):
        self.node['globalProperties']['defineconstants'] = 'OTHER'
        self.rejected('configuration')

    def test_debug_rejected(self):
        self.node['globalProperties']['configuration'] = 'Debug'
        self.rejected('configuration')

    def test_nonstandard_output_layout(self):
        self.node['outputs'][0]['path'] = 'workspace/custom/App.dll'
        self.rejected('output layout')

    def test_incomplete_package_restore_rejected(self):
        (self.workspace / 'App/obj/project.assets.json').write_text('{"libraries":{"Example/1.0.0":{"type":"package"}}}')
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
        source.write_text('{"libraries":{},"changed":true}')
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
