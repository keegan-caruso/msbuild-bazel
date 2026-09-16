"""Only a qualified compile-content delta can bypass graph discovery."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from preparation_identity import capture, digest
from preparation_source_update import refresh


class SourceUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve()
        (self.root/'App.csproj').write_text('<Project/>')
        (self.root/'Program.cs').write_text('class First {}')
        self.graph=dict(graphInputs=[],nodes=[dict(inputs=[dict(kind=kind,path='workspace/'+name,
            sha256=hashlib.sha256((self.root/name).read_bytes()).hexdigest()) for kind,name in [('project','App.csproj'),('source','Program.cs')]])])
        self.candidate=dict(identity=self.snapshot(),graphSha256=digest(self.graph),sha256='a'*64)

    def snapshot(self):
        return capture({'workspace':self.root},request={},environment={},host={})

    def test_content_update_matches_fresh_manifest_hashes(self):
        (self.root/'Program.cs').write_text('class Changed {}')
        result,certificate=refresh(self.candidate,self.graph,self.snapshot())
        expected=copy.deepcopy(self.graph)
        expected['nodes'][0]['inputs'][1]['sha256']=hashlib.sha256((self.root/'Program.cs').read_bytes()).hexdigest()
        self.assertEqual(result,expected)
        self.assertEqual(certificate['graphSha256'],digest(expected))
        self.assertEqual(certificate['derivation']['changedSources'],['workspace/Program.cs'])
        self.assertEqual(self.graph['nodes'][0]['inputs'][1]['sha256'],hashlib.sha256(b'class First {}').hexdigest())

    def test_membership_import_mode_and_undeclared_content_changes_reject(self):
        for mutation in ('add','project','mode','unlisted'):
            with self.subTest(mutation=mutation):
                before={p:p.read_bytes() for p in self.root.iterdir()}
                if mutation=='add':(self.root/'New.cs').write_text('class New {}')
                elif mutation=='project':(self.root/'App.csproj').write_text('<Project>changed</Project>')
                elif mutation=='mode':(self.root/'Program.cs').chmod(0o744)
                else:(self.root/'unlisted.txt').write_text('extra')
                self.assertIsNone(refresh(self.candidate,self.graph,self.snapshot()))
                for p in self.root.iterdir():
                    if p not in before:p.unlink()
                    else:p.write_bytes(before[p]);p.chmod(0o644)

    def test_source_with_another_role_and_resource_graphs_reject(self):
        for kind in ('import','resource','additional'):
            graph=copy.deepcopy(self.graph);graph['nodes'][0]['inputs'].append(dict(kind=kind,path='workspace/Program.cs',sha256='b'*64))
            candidate=dict(self.candidate,graphSha256=digest(graph))
            (self.root/'Program.cs').write_text('class Changed {}')
            self.assertIsNone(refresh(candidate,graph,self.snapshot()))

    def test_changed_invocation_and_mismatched_graph_reject(self):
        (self.root/'Program.cs').write_text('class Changed {}')
        self.assertIsNone(refresh(self.candidate,self.graph,capture({'workspace':self.root},request={'changed':True},environment={},host={})))
        graph=copy.deepcopy(self.graph);graph['extra']='corrupt'
        self.assertIsNone(refresh(self.candidate,graph,self.snapshot()))
