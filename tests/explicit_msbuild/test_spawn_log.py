import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('spawn_log', Path(__file__).parent/'aspnetcore/spawn_log.py')
spawn_log = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spawn_log)

class SpawnLogTests(unittest.TestCase):
    def read(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'log.json'
            path.write_text(text)
            return list(spawn_log.actions(path))

    def test_adjacent_records_without_separator(self):
        records = [{'mnemonic': 'MSBuildAssembly', 'nested': {'text': '}{'}}, {'cacheHit': True}, {'exitCode': 0}]
        self.assertEqual(records, self.read(''.join(json.dumps(row, indent=2) for row in records)))

    def test_newline_separated_and_empty_logs(self):
        self.assertEqual([{'a': 1}, {'b': 2}], self.read('{\n  "a": 1\n}\n{\n  "b": 2\n}\n'))
        self.assertEqual([], self.read(''))

    def test_truncated_record(self):
        with self.assertRaises(ValueError):
            self.read('{\n  "a": 1')

if __name__ == '__main__':
    unittest.main()
