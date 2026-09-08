"""Conventional C# analyzer payloads retain package integrity boundaries."""
import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
import graph_packages


class AnalyzerPackageIntegrity(unittest.TestCase):
    def make_package(self, root, path='analyzers/dotnet/cs/Fixture.dll'):
        (root / 'App/obj').mkdir(parents=True)
        (root / 'App/App.csproj').write_text('<Project><ItemGroup><PackageReference Include="Fixture" Version="[1.0.0]" /></ItemGroup></Project>')
        folder = root / '.nuget/packages/fixture/1.0.0'
        folder.mkdir(parents=True)
        archive = folder / 'fixture.1.0.0.nupkg'
        with zipfile.ZipFile(archive, 'w') as package:
            package.writestr(path, b'fixture-payload')
        payload = folder / path
        payload.parent.mkdir(parents=True, exist_ok=True)
        payload.write_bytes(b'fixture-payload')
        (root / 'App/obj/project.assets.json').write_text(json.dumps({
            'project': {'frameworks': {'net10.0': {'dependencies': {'Fixture': {}}}}},
            'libraries': {'Fixture/1.0.0': {'type':'package', 'path':'fixture/1.0.0',
                'sha512':base64.b64encode(hashlib.sha512(archive.read_bytes()).digest()).decode()}},
            'targets': {'net10.0': {'Fixture/1.0.0': {}}}}))
        return payload, archive

    def test_declared_analyzer_payload_and_corruption_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            payload, archive = self.make_package(root)
            manifest, files = graph_packages.stage(root, 'App/App.csproj', root/'good', 'app')
            self.assertIn('packages/fixture/1.0.0/analyzers/dotnet/cs/Fixture.dll', files)
            self.assertTrue((root/'good'/manifest).exists())
            payload.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'hash-mismatch: package payload'):
                graph_packages.stage(root, 'App/App.csproj', root/'corrupt', 'app')
            payload.unlink()
            with self.assertRaisesRegex(ValueError, 'missing-input'):
                graph_packages.stage(root, 'App/App.csproj', root/'missing', 'app')
            archive.write_bytes(b'wrong-archive')
            with self.assertRaisesRegex(ValueError, 'hash-mismatch: package archive disagrees with restore'):
                graph_packages.stage(root, 'App/App.csproj', root/'archive', 'app')
            for name in ('corrupt', 'missing', 'archive'):
                self.assertFalse((root/name/'package-manifests/app.json').exists())

    def test_unqualified_analyzer_layouts_and_tools_remain_rejected(self):
        for path in ('analyzers/dotnet/roslyn4.0/cs/Fixture.dll', 'analyzers/dotnet/cs/run.sh', 'analyzers/Fixture.dll', 'analyzers/dotnet/cs//Fixture.dll', 'tools/Fixture.dll'):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                self.make_package(root, path)
                with self.assertRaisesRegex(ValueError, 'unsupported-package'):
                    graph_packages.stage(root, 'App/App.csproj', root/'out', 'app')
