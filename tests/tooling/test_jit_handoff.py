"""Preparation handoffs retain declared authored membership and executable modes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'graph_build/upstream/runtime_jit_public_consumer.py'
spec = importlib.util.spec_from_file_location('jit_handoff', SCRIPT)
handoff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(handoff)


class JitHandoff(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / 'producer'
        for name in ['workspace', 'bootstrap']:
            root = self.source / name
            root.mkdir(parents=True)
            values = {'Code.cs': 'class C {}', 'Extra.props': '<Project/>', 'task.sh': '#!/bin/sh\ntrue\n',
                'BUILD.bazel': '', 'graph.generated.bzl': '', 'NuGet.config': '<configuration/>',
                'MODULE.bazel': 'local_path_override(module_name="rules_msbuild",path="/old/rules")',
                'MODULE.bazel.lock': '{}', 'mappings.json': '{}', 'nuget.lock.json': '{}',
                'graph.generated.json': json.dumps(dict(SharedInputs=['NuGet.config'], Projects={
                    'Test.csproj': dict(Inputs=['Code.cs'], Configurations=[])})),
                'jit-public.json': json.dumps(dict(sourceProducer={'module': 'jit_source_runtime'}))}
            for filename, text in values.items():
                (root / filename).write_text(text)
            (root / 'task.sh').chmod(0o755)
            (root / 'bin').mkdir()
            (root / 'bin/unwanted.dll').write_bytes(b'output')
        native = self.source / 'source_runtime'
        native.mkdir()
        (native / 'MODULE.bazel').write_text('local_path_override(module_name="rules_msbuild",path="/old/rules")')
        (native / 'source.tar').write_bytes(b'declared input')
        self.seed = self.base / 'seed.json'
        self.seed.write_text(json.dumps(dict(sourceDigests={'Code.cs': hashlib.sha256(b'class C {}').hexdigest()})))
        self.output = self.base / 'consumer'

    def run_handoff(self, preparation):
        command = ['handoff', str(self.source), str(self.seed), str(self.output)]
        if preparation:
            command += ['--preparation-base', str(self.base / 'query')]
        with patch.object(sys, 'argv', command), patch.object(handoff, 'preparation_sources',
                return_value={'Extra.props', 'task.sh'}):
            handoff.main()

    def test_preparation_retains_membership_modes_locks_and_omits_outputs(self):
        self.run_handoff(True)
        for name in ['workspace', 'bootstrap']:
            root = self.output / name
            self.assertEqual((root / 'Extra.props').read_text(), '<Project/>')
            self.assertEqual((root / 'task.sh').stat().st_mode & 0o777, 0o755)
            self.assertTrue((root / 'MODULE.bazel.lock').is_file())
            self.assertFalse((root / 'bin').exists())
        self.assertTrue(json.loads((self.output / 'consumer.json').read_text())['preparationSnapshot'])

    def test_normal_build_handoff_remains_closed_to_declared_inputs(self):
        self.run_handoff(False)
        self.assertFalse((self.output / 'workspace/Extra.props').exists())
        self.assertFalse((self.output / 'workspace/task.sh').exists())

    def test_authored_link_rejected(self):
        path = self.source / 'workspace/Code.cs'
        path.unlink()
        path.symlink_to(self.source / 'bootstrap/Code.cs')
        with self.assertRaises(AssertionError):
            self.run_handoff(True)

    def test_query_rejects_another_repository(self):
        with patch.object(handoff.subprocess, 'check_output', return_value='@other//:Source.cs\n'), \
                patch.object(handoff.subprocess, 'run'):
            with self.assertRaises(AssertionError):
                handoff.preparation_sources(self.source / 'workspace', self.base / 'query')


if __name__ == '__main__':
    unittest.main()
