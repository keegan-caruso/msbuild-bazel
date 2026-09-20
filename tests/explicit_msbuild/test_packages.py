"""Archive integrity and identity controls for the explicit package action."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]


class PackageIntegrity(unittest.TestCase):
    def extract(self, mutation=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = io.BytesIO()
            with zipfile.ZipFile(data, 'w') as archive:
                archive.writestr('example.nuspec', '<package><metadata><id>Example</id><version>1.0.0</version></metadata></package>')
                archive.writestr('../escape' if mutation == 'traversal' else 'lib/net10.0/Example.dll', b'fixture')
            payload = data.getvalue()
            (root/'input.nupkg').write_bytes(payload)
            request = dict(id='Wrong' if mutation == 'identity' else 'Example', version='1.0.0',
                archive=str(root/'input.nupkg'), contentHash=base64.b64encode(hashlib.sha512(payload).digest()).decode(),
                archiveSha256='0'*64 if mutation == 'hash' else hashlib.sha256(payload).hexdigest(), output=str(root/'output'))
            (root/'request.json').write_text(json.dumps(request))
            result = subprocess.run([str(Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT/'.tools/dotnet'))/'dotnet'),
                str(ROOT/'tools/ExplicitBuild/bin/Release/net10.0/ExplicitBuild.dll'), 'extract', str(root/'request.json')], capture_output=True, text=True)
            if mutation is None:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual((root/'output/lib/net10.0/Example.dll').read_bytes(), b'fixture')
            else:
                self.assertNotEqual(result.returncode, 0)
                self.assertIn({'hash': 'locked archive hash', 'identity': 'identity differs', 'traversal': 'Unsafe logical path'}[mutation], result.stderr)
                self.assertFalse((root/'escape').exists())

    def test_valid_archive(self):
        self.extract()

    def test_changed_archive(self):
        self.extract('hash')

    def test_wrong_identity(self):
        self.extract('identity')

    def test_path_traversal(self):
        self.extract('traversal')


if __name__ == '__main__':
    unittest.main()
