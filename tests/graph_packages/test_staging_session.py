"""Repeated package consumers keep integrity checks under one preparation."""
import json
import mmap
from pathlib import Path
import tempfile
import unittest
import test_analyzer_packages as fixtures
import graph_packages


class StagingSessionTests(unittest.TestCase):
    def fixture(self, root):
        return fixtures.AnalyzerPackageIntegrity().make_package(root)

    def test_shared_package_bytes_and_manifests_match_independent_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();self.fixture(root)
            output=root/'shared';session=graph_packages.StagingSession(root,output)
            for node in ('left','right'):
                actual=graph_packages.stage(root,'App/App.csproj',output,node,session=session)
                expected=graph_packages.stage(root,'App/App.csproj',root/node,node)
                self.assertEqual(actual,expected)
                for path in [actual[0],*actual[1]]:
                    self.assertEqual((output/path).read_bytes(),(root/node/path).read_bytes())
            self.assertEqual(len(session.packages),1)
            session.verify()
            with self.assertRaisesRegex(ValueError,'another preparation'):
                graph_packages.stage(root,'App/App.csproj',output,'closed',session=session)

    def test_mutation_after_first_consumer_rejects_before_publication(self):
        for change in ('payload','archive','new-bookkeeping'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as directory:
                root=Path(directory).resolve();payload,archive=self.fixture(root)
                output=root/'output';session=graph_packages.StagingSession(root,output)
                graph_packages.stage(root,'App/App.csproj',output,'first',session=session)
                if change=='payload':payload.write_bytes(b'corrupted')
                elif change=='archive':archive.write_bytes(b'corrupted')
                else:(archive.parent/'[Content_Types].xml').write_bytes(b'new')
                graph_packages.stage(root,'App/App.csproj',output,'second',session=session)
                with self.assertRaisesRegex(ValueError,'package changed'):
                    session.verify()

    def test_second_consumer_with_conflicting_restore_hash_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();self.fixture(root)
            output=root/'output';session=graph_packages.StagingSession(root,output)
            graph_packages.stage(root,'App/App.csproj',output,'first',session=session)
            path=root/'App/obj/project.assets.json';assets=json.loads(path.read_text())
            assets['libraries']['Fixture/1.0.0']['sha512']='corrupt'
            path.write_text(json.dumps(assets))
            with self.assertRaisesRegex(ValueError,'archive disagrees'):
                graph_packages.stage(root,'App/App.csproj',output,'second',session=session)

    def test_mapped_content_change_rejects_without_timestamp_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();payload,_=self.fixture(root)
            with payload.open('r+b') as stream, mmap.mmap(stream.fileno(),0) as mapped:
                output=root/'output';session=graph_packages.StagingSession(root,output)
                graph_packages.stage(root,'App/App.csproj',output,'first',session=session)
                mapped[0] = mapped[0] ^ 1
                with self.assertRaisesRegex(ValueError,'package changed'):
                    session.verify()
