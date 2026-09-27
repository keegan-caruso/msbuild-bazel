"""The component handoff must carry only declared artifacts and fail closed."""
from pathlib import Path
import tarfile
import tempfile
import unittest

from component_outputs import bundle, published_files


class ComponentOutputsTests(unittest.TestCase):
    def fixture(self, root, path='artifacts/packages/one/a.nupkg', origin='one'):
        manifest = root / 'artifacts/obj/manifests/Release/one/linux.xml'
        manifest.parent.mkdir(parents=True)
        manifest.write_text('<Build><Package Id="A" Version="1.0.0" RepoOrigin="' + origin + '" PipelineArtifactPath="' + path + '" /></Build>')
        package = root / 'artifacts/packages/one/a.nupkg'
        package.parent.mkdir(parents=True)
        package.write_bytes(b'package')

    def test_manifest_and_own_payload_only_with_stable_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / 'unrelated').write_text('not an output')
            first = bundle(root, 'one', root / 'first.tar')
            second = bundle(root, 'one', root / 'second.tar')
            self.assertEqual(first, second)
            with tarfile.open(root / 'first.tar') as archive:
                self.assertEqual(len(archive.getnames()), 2)
                self.assertIn('artifacts/packages/one/a.nupkg', archive.getnames())

    def test_legacy_package_manifest_uses_upstream_shipping_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            manifest = root / 'artifacts/obj/manifests/Release/one/linux.xml'
            manifest.write_text('<Build PublishingVersion="3"><Package Id="A" Version="1.0.0" NonShipping="true" RepoOrigin="one" /></Build>')
            package = root / 'artifacts/packages/Release/NonShipping/one/A.1.0.0.nupkg'
            package.parent.mkdir(parents=True)
            package.write_bytes(b'legacy')
            self.assertIn(str(package.relative_to(root)), published_files(root, 'one'))

    def test_missing_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / 'artifacts/packages/one/a.nupkg').unlink()
            with self.assertRaisesRegex(ValueError, 'Missing'):
                published_files(root, 'one')

    def test_manifest_cannot_escape_or_claim_another_component(self):
        for path, origin in [('artifacts/../../secret', 'one'), ('/secret', 'one'), ('artifacts/packages/one/a.nupkg', 'other')]:
            with self.subTest(path=path, origin=origin), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                self.fixture(root, path, origin)
                with self.assertRaises(ValueError):
                    published_files(root, 'one')


if __name__ == '__main__':
    unittest.main()
