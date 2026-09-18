import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from native_staging import Staging


class StagingTests(unittest.TestCase):
    def test_unchanged_bytes_keep_inode_and_removed_inputs_are_pruned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'g'
            first = Staging(root)
            first.write('src/keep', b'unchanged'); first.write('seeds/old', b'old'); first.finish()
            before = (root / 'src/keep').stat()
            second = Staging(root); second.write('src/keep', b'unchanged')
            self.assertEqual(second.finish(), dict(written=0, retained=1))
            after = (root / 'src/keep').stat()
            self.assertEqual((before.st_ino, before.st_mtime_ns), (after.st_ino, after.st_mtime_ns))
            self.assertFalse((root / 'seeds').exists())
            (root / 'src/keep').write_bytes(b'corrupted')
            third = Staging(root); third.write('src/keep', b'unchanged'); third.finish()
            self.assertEqual((root / 'src/keep').read_bytes(), b'unchanged')

    def test_linked_inputs_never_write_through(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'g'; outside = Path(temp) / 'outside'; outside.mkdir()
            stage = Staging(root); (root / 'src').symlink_to(outside)
            with self.assertRaisesRegex(ValueError, 'linked'): stage.write('src/p', b'bad')
            self.assertFalse((outside / 'p').exists())

class BorrowedPayloadTests(unittest.TestCase):
    def test_mutation_during_borrow_rejects_before_success(self):
        import json
        from contextlib import contextmanager
        from unittest.mock import patch
        import preparation_reuse as reuse
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); source = root / 'source'; source.mkdir()
            generation = root / 'generation'; payload = generation / 'payload'; payload.mkdir(parents=True)
            (payload / 'file').write_bytes(b'original')
            manifest = dict(certificate={}, payloadSha256=reuse.payload_identity(payload))
            @contextmanager
            def qualified(*args, **kwargs): yield dict(unchanged=True)
            with patch.object(reuse.prepare_graph, 'DOTNET_ROOT', reuse.discovery.SDK), \
                 patch.object(reuse, 'tool_identity', return_value={}), \
                 patch.object(reuse, 'read_candidate', return_value=((generation, manifest), None)), \
                 patch.object(reuse.discovery, 'qualified_view', side_effect=qualified):
                with self.assertRaisesRegex(ValueError, 'payload changed during consumption'):
                    with reuse.prepared_view(source, root / 'state', root / 'out',
                            [dict(project='App.csproj', globalProperties={'Configuration': 'Release', 'TargetFramework': 'net10.0'})],
                            native_toolchain='a' * 64, borrow_native=True) as result:
                        self.assertEqual(Path(result['workspace']), payload)
                        self.assertFalse((root / 'out').exists())
                        (payload / 'file').write_bytes(b'corrupt')
