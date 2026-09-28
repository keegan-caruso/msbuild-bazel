"""Determinism and link-boundary checks for the AOT archive derivation."""

import hashlib
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

from native_toolchain_archive import archive, digest_tree, entries


class NativeToolchainArchiveTests(unittest.TestCase):
    def test_selected_archive_is_deterministic_and_self_contained(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "tree"
            (root / "usr/bin").mkdir(parents=True)
            (root / "usr/lib/aarch64-linux-gnu/icu/70.1").mkdir(parents=True)
            (root / "usr/bin/dash").write_text("shell")
            (root / "usr/bin/dash").chmod(0o755)
            (root / "usr/bin/sh").symlink_to("dash")
            (root / "usr/bin/clang").symlink_to("/host/clang")
            (root / "usr/bin/objcopy").symlink_to("../../../../host/objcopy")
            (root / "usr/bin/unrelated").write_text("unused")
            (root / "secret").write_text("unused")
            (root / "usr/lib/aarch64-linux-gnu/libm.a").write_text("math")
            (root / "usr/lib/aarch64-linux-gnu/libicudata.a").write_text("unused")
            (root / "usr/lib/aarch64-linux-gnu/icu/70.1/pkgdata.inc").write_text("icu")
            (root / "usr/lib/aarch64-linux-gnu/icu/current").symlink_to("70.1", target_is_directory=True)
            (root / "usr/lib/aarch64-linux-gnu/icu/pkgdata.inc").symlink_to("current/pkgdata.inc")
            (root / "etc").mkdir()
            (root / "etc/os-release").write_text("Ubuntu")
            (root / "etc/shadow").write_text("secret")

            selected = {str(path) for path in entries(root)}
            self.assertIn("usr/bin/sh", selected)
            self.assertIn("usr/lib/aarch64-linux-gnu/icu/current", selected)
            self.assertIn("usr/lib/aarch64-linux-gnu/icu/pkgdata.inc", selected)
            self.assertIn("usr/lib/aarch64-linux-gnu/libm.a", selected)
            self.assertNotIn("usr/bin/clang", selected)
            self.assertNotIn("usr/bin/objcopy", selected)
            self.assertNotIn("usr/bin/unrelated", selected)
            self.assertNotIn("secret", selected)
            self.assertNotIn("usr/lib/aarch64-linux-gnu/libicudata.a", selected)
            self.assertNotIn("etc/shadow", selected)

            first = Path(temporary) / "first.tar.gz"
            second = Path(temporary) / "second.tar.gz"
            archive(root, first)
            archive(root, second)
            self.assertEqual(hashlib.sha256(first.read_bytes()).digest(), hashlib.sha256(second.read_bytes()).digest())
            with tarfile.open(first, "r:gz") as packaged:
                self.assertEqual({member.name for member in packaged}, selected)
                self.assertTrue(all(member.mtime == 0 and member.uid == 0 and member.gid == 0 for member in packaged))
                self.assertEqual(packaged.getmember("usr/bin/dash").mode, 0o755)

            rejected = Path(temporary) / "rejected.tar.gz"
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("native_toolchain_archive.py")), str(root), str(rejected), "--expected-tree-sha256", "0" * 64],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("selected source tree differs", result.stderr)
            self.assertFalse(rejected.exists())
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("native_toolchain_archive.py")), str(root), str(root / "usr/toolchain.tar.gz"), "--expected-tree-sha256", digest_tree(root)],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("outside the source tree", result.stderr)
            self.assertFalse((root / "usr/toolchain.tar.gz").exists())
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("native_toolchain_archive.py")), str(root), str(rejected), "--expected-tree-sha256", digest_tree(root), "--expected-archive-sha256", "0" * 64],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("archive differs from locked", result.stderr)
            self.assertFalse(rejected.exists())


if __name__ == "__main__":
    unittest.main()
