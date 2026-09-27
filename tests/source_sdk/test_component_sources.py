import hashlib
import io
from pathlib import Path
import tarfile
import tempfile
import unittest

from component_sources import includes, select


class ComponentSourcesTests(unittest.TestCase):
    def test_implementation_changes_are_scoped_but_shared_build_inputs_remain(self):
        self.assertTrue(includes('src/command-line-api/src/Command.cs', 'command-line-api'))
        self.assertFalse(includes('src/command-line-api/src/Command.cs', 'arcade'))
        self.assertTrue(includes('src/command-line-api/Directory.Build.props', 'arcade'))
        self.assertTrue(includes('src/arcade/eng/common/build.sh', 'command-line-api'))
        self.assertTrue(includes('eng/tools/tasks/Task.cs', 'command-line-api'))
        self.assertFalse(includes('build-native.sh', 'command-line-api'))

    def test_other_component_body_edit_preserves_archive_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            results = []
            for revision in ['before', 'after']:
                source = root / (revision + '.tar')
                with tarfile.open(source, 'w') as archive:
                    for name, data in [('src/arcade/A.cs', b'unchanged'), ('src/command-line-api/C.cs', revision.encode()), ('eng/Versions.props', b'shared')]:
                        entry = tarfile.TarInfo(name)
                        entry.size = len(data)
                        archive.addfile(entry, io.BytesIO(data))
                row = {}
                for component in ['arcade', 'command-line-api']:
                    output = root / (revision + '-' + component + '.tar')
                    select(source, component, output, [])
                    row[component] = hashlib.sha256(output.read_bytes()).hexdigest()
                results.append(row)
            self.assertEqual(results[0]['arcade'], results[1]['arcade'])
            self.assertNotEqual(results[0]['command-line-api'], results[1]['command-line-api'])
