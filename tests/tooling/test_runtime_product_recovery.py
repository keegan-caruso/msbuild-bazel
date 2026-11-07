"""A source-runtime handoff must not borrow producer build outputs."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

UPSTREAM = Path(__file__).resolve().parents[1]/'graph_build/upstream'
sys.path.insert(0, str(UPSTREAM))
spec = importlib.util.spec_from_file_location('runtime_product_recovery', UPSTREAM/'runtime_product_recovery.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class ProductRecovery(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base/'producer'
        files = ['BUILD.bazel', 'MODULE.bazel', 'MODULE.bazel.lock', 'graph.generated.bzl',
            'nuget.lock.json', 'runtime-product.json', 'runtime_product.bzl', 'runtime_product_test.py',
            'source_repository.bzl', 'LICENSE.TXT', 'THIRD-PARTY-NOTICES.TXT', 'Code.cs',
            'native/BUILD.bazel', 'native/native_action.bzl', 'native/native_inputs.bzl',
            'native/coreclr.sh', 'native/libraries.sh', 'native/host.sh', 'libraries/BUILD.bazel',
            'host/BUILD.bazel', 'app/Code.cs', 'native/Task.cs']
        for name in files:
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        (self.root/'MODULE.bazel').write_text('local_path_override(module_name="rules_msbuild",path="/producer/rules")\n'
            'runtime_source(urls=["file:///producer/source.tar.gz", "https://example.invalid/source.tar.gz"])')
        (self.root/'graph.generated.json').write_text(json.dumps(dict(SharedInputs=[],
            Projects={'Project.csproj': dict(Inputs=['Code.cs'])})))
        for folder, name, source in [('app', 'contract.json', 'Code.cs'), ('native', 'driver-contract.json', 'Task.cs')]:
            (self.root/folder/name).write_text(json.dumps(dict(SharedInputs=[], Projects={'Project.csproj': dict(Inputs=[source])})))
        (self.root/'native/coreclr.sh').chmod(0o755)
        for name in ['bazel-bin/output.dll', 'app/bin/App.dll', 'native/obj/Task.dll']:
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'producer output must stay behind')

    def test_closure_omits_outputs_and_retains_source_modes(self):
        target = self.base/'consumer'
        recovery.close(self.root, target)
        self.assertFalse((target/'bazel-bin').exists())
        self.assertFalse((target/'app/bin').exists())
        self.assertFalse((target/'native/obj').exists())
        self.assertEqual((target/'native/coreclr.sh').stat().st_mode & 0o777, 0o755)
        self.assertEqual((target/'Code.cs').read_bytes(), (self.root/'Code.cs').read_bytes())
        self.assertNotIn('/producer/', (target/'MODULE.bazel').read_text())
        self.assertIn('https://example.invalid/source.tar.gz', (target/'MODULE.bazel').read_text())

    def test_sync_closure_uses_authored_query_membership(self):
        target = self.base/'sync-consumer'
        with patch.object(recovery, 'preparation_sources', return_value={'Code.cs', 'native/coreclr.sh'}):
            recovery.close_sync(self.root, target, self.base/'query')
        self.assertEqual((target/'Code.cs').read_bytes(), (self.root/'Code.cs').read_bytes())
        self.assertEqual((target/'native/coreclr.sh').stat().st_mode & 0o777, 0o755)
        self.assertFalse((target/'app').exists())
        self.assertFalse((target/'native/obj').exists())
        self.assertFalse((target/'runtime-product.json').exists())

    def test_declared_symlink_is_rejected(self):
        source = self.root/'Code.cs'
        source.unlink()
        source.symlink_to(self.root/'app/Code.cs')
        with self.assertRaisesRegex(ValueError, 'independent workspace file'):
            recovery.close(self.root, self.base/'rejected')


if __name__ == '__main__':
    unittest.main()
