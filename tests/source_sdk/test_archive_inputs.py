"""PAX metadata must not undo normalized VMR paths or reproducible metadata."""
import io
import tarfile
import unittest

from source_action_prepare import normalize


class ArchiveInputsTests(unittest.TestCase):
    def test_pax_headers_cannot_restore_old_source_prefix(self):
        entry = tarfile.TarInfo('src/' + 'long-name-' * 20 + '.cs')
        entry.size = 4
        entry.pax_headers = {'path': 'old-prefix/' + entry.name, 'mtime': '1234', 'uid': '42'}
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode='w') as archive:
            archive.addfile(normalize(entry), io.BytesIO(b'code'))
        output.seek(0)
        with tarfile.open(fileobj=output, mode='r') as archive:
            actual = next(iter(archive))
            self.assertEqual(actual.name, entry.name)
            self.assertEqual(actual.uid, 0)
            self.assertEqual(actual.mtime, 0)
            self.assertEqual(archive.extractfile(actual).read(), b'code')


if __name__ == '__main__':
    unittest.main()
