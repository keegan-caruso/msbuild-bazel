"""Protected generations are explicit, process-local and never disk receipts."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from preparation_identity import tree_snapshot
from protected_store import ProtectedStore


class ProtectedStoreTests(unittest.TestCase):
    def test_user_owned_input_always_hashes_and_detects_restored_mtime(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();source=root/'value';source.write_text('first')
            store=ProtectedStore();before=store.snapshot(root,[root]);stamp=source.stat()
            source.write_text('other');os.utime(source,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
            after=store.snapshot(root,[root])
            self.assertNotEqual(before['sha256'],after['sha256'])
            self.assertEqual(store.hits,0)
            self.assertFalse(store.cache)

    def test_protected_cache_is_process_local_and_defensively_copied(self):
        # Protection is mocked only here; native qualification uses the real
        # system-owned store and rejects writable copies.
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory).resolve();(root/'file').write_text('value')
            store=ProtectedStore();value=tree_snapshot(root)
            from preparation_identity import _signature
            key=(str(root),(str(root),));store.cache[key]=(_signature(root.lstat()),value)
            with patch.object(store,'eligible_root',return_value=True):
                result=store.snapshot(root,[root]);result['entries'].clear()
                self.assertEqual(store.snapshot(root,[root]),value)
                self.assertEqual(store.hits,2)
            self.assertFalse(ProtectedStore().cache)
            store.pid=-1
            self.assertFalse(store.eligible_root(root))
