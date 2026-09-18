import mmap
import os
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from invocation_identity import InvocationIdentity


class InvocationIdentityTests(unittest.TestCase):
    def test_mmap_mutation_with_restored_mtime_rejects_at_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path = root / 'tool'; path.write_bytes(b'old')
            session = InvocationIdentity([root]); before = path.stat()
            first = session.snapshot(root, [root])
            with path.open('r+b') as stream, mmap.mmap(stream.fileno(), 0) as view:
                view[:] = b'new'; view.flush()
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
            self.assertEqual(session.snapshot(root, [root]), first)
            with self.assertRaisesRegex(ValueError, 'changed during consumption'): session.verify()

    def test_same_bytes_reuse_and_final_check_then_close(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / 'file').write_bytes(b'same')
            session = InvocationIdentity([root]); session.snapshot(root, [root]); session.snapshot(root, [root])
            self.assertEqual(session.hits, 1); session.verify()
            with self.assertRaisesRegex(ValueError, 'closed'): session.snapshot(root, [root])

    def test_broader_allowed_domain_cannot_authorize_narrower_reuse(self):
        with tempfile.TemporaryDirectory() as temp:
            outer = Path(temp); root = outer / 'root'; root.mkdir()
            (outer / 'external').write_bytes(b'outside'); (root / 'link').symlink_to(outer / 'external')
            session = InvocationIdentity([root]); session.snapshot(root, [outer])
            with self.assertRaisesRegex(ValueError, 'undeclared symlink'): session.snapshot(root, [root])

    def test_mutable_source_is_always_read_and_new_membership_rejects(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path = root / 'file'; path.write_bytes(b'old')
            session = InvocationIdentity(); first = session.snapshot(root, [root]); path.write_bytes(b'new')
            self.assertNotEqual(session.snapshot(root, [root]), first)
            checked = InvocationIdentity([root]); checked.snapshot(root, [root]); (root / 'new').mkdir()
            with self.assertRaisesRegex(ValueError, 'changed during consumption'): checked.verify()
