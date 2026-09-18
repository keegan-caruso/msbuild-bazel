import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from native_graph import materialize, refresh_sources
from preparation_identity import capture, digest
from preparation_reuse import payload_identity
from preparation_source_update import refresh


class NativeRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.source = self.root / 'source'; self.source.mkdir()
        (self.source / 'App.csproj').write_text('<Project/>')
        (self.source / 'Program.cs').write_text('class First {}')
        self.graph = dict(entryPoints=['a'], graphInputs=[], nodes=[dict(id='a', project='workspace/App.csproj',
            globalProperties={'configuration': 'Release', 'targetframework': 'net10.0'}, targetFramework='net10.0', outputType='Library',
            execution=dict(outputDirectory='workspace/bin/Release/net10.0', referenceDirectory='workspace/obj/Release/net10.0/ref'),
            outputs=[dict(kind='assembly', path='workspace/bin/Release/net10.0/App.dll')], dependencies=[],
            inputs=[dict(kind=kind, path='workspace/' + name, sha256=hashlib.sha256((self.source / name).read_bytes()).hexdigest())
                    for kind, name in [('project', 'App.csproj'), ('source', 'Program.cs')]])])
        self.before = dict(identity=self.snapshot(), graphSha256=digest(self.graph), sha256='a' * 64)
        self.prepared = self.root / 'prepared'
        import shutil
        shutil.copytree(self.source, self.prepared / 'src')
        for directory in ('restore', 'package-manifests'): (self.prepared / directory).mkdir()
        (self.prepared / 'restore/a.json').write_text(json.dumps({'obj/project.assets.json': '{}'}))
        (self.prepared / 'package-manifests/a.json').write_text(json.dumps(dict(schemaVersion=1, packages=[])))
        self.previous = self.root / 'previous'
        materialize(self.prepared, self.graph, self.previous, 'b' * 64)
        self.payload_hash = payload_identity(self.previous)
        (self.source / 'Program.cs').write_text('class Changed {}')
        self.updated, self.certificate = refresh(self.before, self.graph, self.snapshot())

    def snapshot(self): return capture({'workspace': self.source}, request={}, environment={}, host={})

    def run_refresh(self):
        return refresh_sources(self.previous, self.source, self.updated, self.root / 'refreshed', 'b' * 64,
            certificate=self.certificate, previous_certificate=self.before, payload_sha256=self.payload_hash)

    def test_refreshed_payload_matches_full_materialization(self):
        actual = self.run_refresh()
        (self.prepared / 'src/Program.cs').write_bytes((self.source / 'Program.cs').read_bytes())
        expected = materialize(self.prepared, self.updated, self.root / 'fresh', 'b' * 64)
        self.assertEqual(actual, expected)
        for p in (self.root / 'fresh').rglob('*'):
            if p.is_file(): self.assertEqual(p.read_bytes(), (self.root / 'refreshed' / p.relative_to(self.root / 'fresh')).read_bytes())

    def test_corrupt_previous_package_or_input_is_rejected(self):
        (self.previous / 'src/Program.cs').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'payload changed'): self.run_refresh()

    def test_post_capture_source_mutation_is_rejected(self):
        (self.source / 'Program.cs').write_text('class Late {}')
        with self.assertRaisesRegex(ValueError, 'source changed'): self.run_refresh()

    def test_non_source_graph_change_is_rejected(self):
        self.updated['nodes'][0]['outputType'] = 'Exe'
        with self.assertRaisesRegex(ValueError, 'qualified derivation'): self.run_refresh()

    def test_package_namespace_change_is_not_a_refresh(self):
        (self.source / 'package.targets').write_text('changed package')
        self.assertIsNone(refresh(self.before, self.graph, self.snapshot()))
