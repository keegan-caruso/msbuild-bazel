"""Check verified raw input and stock-project bootstrap handoff."""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from prepare_x64_bootstrap import prepare


class BootstrapPreparationTests(unittest.TestCase):
    def fixture(self, root, props=True):
        archive = root / 'prereqs/packages/archive/raw.tar.gz'
        archive.parent.mkdir(parents=True)
        with tarfile.open(archive, 'w:gz') as bundle:
            data = b'<Project />'
            entry = tarfile.TarInfo('PackageVersions.props' if props else 'other.props')
            entry.size = len(data)
            bundle.addfile(entry, io.BytesIO(data))
        for name in ['eng/bootstrap/buildBootstrapPreviouslySB.csproj', 'src/sdk/NuGet.config']:
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        return {'previouslySourceBuiltArtifacts': {'url': 'https://fixture.invalid/raw.tar.gz',
                 'bytes': archive.stat().st_size, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}}

    def output(self, root, include_package=True):
        path = root / 'prereqs/packages/archive/Private.SourceBuilt.Artifacts.Bootstrap.tar.gz'
        with tarfile.open(path, 'w:gz') as bundle:
            for name in ['PackageVersions.props'] + (['runtime.linux-x64.fixture.1.nupkg'] if include_package else []):
                data = name.encode()
                entry = tarfile.TarInfo(name)
                entry.size = len(data)
                bundle.addfile(entry, io.BytesIO(data))

    def test_stock_restore_uses_pinned_inputs_and_records_generated_member_hashes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = self.fixture(root)
            def restore(command, **options):
                self.assertEqual(command[:2], [str(root / '.dotnet/dotnet'), 'restore'])
                self.assertEqual(options, {'cwd': root, 'check': True})
                self.assertIn('/p:PortableTargetRid=linux-x64', command)
                self.assertIn('/p:ArchiveDir=' + str(root / 'prereqs/packages/archive') + '/', command)
                working = root / 'artifacts/prep-bootstrap'
                self.assertEqual((working / 'buildBootstrapPreviouslySB.csproj').read_bytes(),
                                 (root / 'eng/bootstrap/buildBootstrapPreviouslySB.csproj').read_bytes())
                self.assertEqual((working / 'NuGet.config').read_bytes(), (root / 'src/sdk/NuGet.config').read_bytes())
                self.assertEqual((working / 'PackageVersions.props').read_bytes(), b'<Project />')
                self.output(root)
            with patch('prepare_x64_bootstrap.subprocess.run', side_effect=restore) as run:
                report = prepare(root, pin)
            run.assert_called_once()
            self.assertEqual(report['rawArchiveSha256'], pin['previouslySourceBuiltArtifacts']['sha256'])
            self.assertEqual(len(report['members']), 2)
            for member in report['members']:
                self.assertEqual(member['sha256'], hashlib.sha256(member['name'].encode()).hexdigest())
            self.assertEqual(json.loads((root / 'artifacts/log/bootstrap-inputs.json').read_text()), report)

    def test_corrupt_raw_input_fails_before_any_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = self.fixture(root)
            (root / 'prereqs/packages/archive/raw.tar.gz').write_bytes(b'changed')
            with patch('prepare_x64_bootstrap.subprocess.run') as run, self.assertRaisesRegex(ValueError, 'identity mismatch'):
                prepare(root, pin)
            run.assert_not_called()
            self.assertFalse((root / 'artifacts').exists())

    def test_existing_generated_input_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = self.fixture(root)
            self.output(root)
            with patch('prepare_x64_bootstrap.subprocess.run') as run, self.assertRaisesRegex(ValueError, 'already exists'):
                prepare(root, pin)
            run.assert_not_called()

    def test_missing_versions_input_fails_before_restore(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = self.fixture(root, props=False)
            with patch('prepare_x64_bootstrap.subprocess.run') as run, self.assertRaisesRegex(ValueError, 'lacks PackageVersions'):
                prepare(root, pin)
            run.assert_not_called()

    def test_generated_archive_requires_both_versions_and_packages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pin = self.fixture(root)
            with patch('prepare_x64_bootstrap.subprocess.run', side_effect=lambda *a, **kw: self.output(root, False)), \
                    self.assertRaisesRegex(ValueError, 'lacks package inventory'):
                prepare(root, pin)


if __name__ == '__main__':
    unittest.main()
