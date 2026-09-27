"""Reject drift and retain conditional dependency semantics in VMR inventory."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from inventory import inventory, repository_references


class InventoryTests(unittest.TestCase):
    def test_nested_conditions_and_reference_operations_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / 'sdk.proj'
            project.write_text('''<Project><ItemGroup Condition="source-only">
              <RepositoryReference Include="runtime" Condition="arm64">
                <BuildReference Condition="stage-two">false</BuildReference>
              </RepositoryReference>
              <RepositoryReference Remove="shared" />
              <RepositoryReference Update="compiler" BuildReference="false" />
            </ItemGroup></Project>''')
            rows = repository_references(project)
            self.assertEqual(rows[0]['conditions'], ['source-only', 'arm64'])
            self.assertEqual(rows[0]['metadata'], [dict(name='BuildReference', value='false', attributes={'Condition': 'stage-two'})])
            self.assertEqual(rows[1]['attributes'], {'Remove': 'shared'})
            self.assertEqual(rows[2]['attributes']['BuildReference'], 'false')

    def test_drift_is_rejected_before_reading_other_inputs(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / 'global.json').write_text('modified')
            pin = {'definitionHashes': {'global.json': hashlib.sha256(b'original').hexdigest()}}
            with self.assertRaisesRegex(ValueError, 'Pinned definition changed: global.json'):
                inventory(source, pin)


if __name__ == '__main__':
    unittest.main()
