"""Source binding must preserve immutable discovery inputs and actual content identity."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class SourceBinding(unittest.TestCase):
    def test_bazel_symlinks_readonly_templates_and_source_identity(self):
        for metadata_only in [False, True]:
            with self.subTest(metadata_only=metadata_only), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); template = root/'template'; template.mkdir()
                empty = hashlib.sha256(b'').hexdigest()
                record = dict(inputs={'workspace/A.cs': empty}, graphInputs=[])
                documents = {
                    'graph.json': dict(nodes=[dict(inputs=[dict(kind='source', path='workspace/A.cs', sha256=empty)])], graphInputs=[]),
                    'identity-records.json': {'App.csproj': record},
                    'manifest.json': dict(projects={'App.csproj': dict(identity=digest(record))}),
                }
                if metadata_only: documents['payload.json'] = {'A.cs': empty}
                for name, value in documents.items(): (template/name).write_text(json.dumps(value))
                if not metadata_only:
                    (template/'src').mkdir(); (template/'src/A.cs').write_bytes(b'')
                sandbox = root/'sandbox'; sandbox.mkdir()
                originals = {}
                for path in template.rglob('*'):
                    if not path.is_file(): continue
                    originals[path] = path.read_bytes(); path.chmod(0o444)
                    target = sandbox/path.relative_to(template); target.parent.mkdir(parents=True, exist_ok=True); target.symlink_to(path)
                source = root/'actual.cs'; source.write_bytes(b'public class A { public int Value => 7; }\n')
                link = root/'source.cs'; link.symlink_to(source)
                output = root/'output'
                request = root/'request.json'; request.write_text(json.dumps(dict(discovery=str(sandbox), output=str(output), sources=[dict(source=str(link), destination='A.cs')])))
                command = [str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'), str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'), 'owned-bind-sources', '--request', str(request)]
                p = subprocess.run(command, capture_output=True, text=True, timeout=30)
                self.assertEqual(p.returncode, 0, p.stderr)
                expected = hashlib.sha256(source.read_bytes()).hexdigest()
                actual_record = json.loads((output/'identity-records.json').read_text())['App.csproj']
                self.assertEqual(actual_record['inputs']['workspace/A.cs'], expected)
                self.assertEqual(json.loads((output/'manifest.json').read_text())['projects']['App.csproj']['identity'], digest(actual_record))
                self.assertEqual(json.loads((output/'graph.json').read_text())['nodes'][0]['inputs'][0]['sha256'], expected)
                if metadata_only:
                    self.assertFalse((output/'src').exists())
                    self.assertEqual(json.loads((output/'payload.json').read_text())['A.cs'], expected)
                else: self.assertEqual((output/'src/A.cs').read_bytes(), source.read_bytes())
                for path, content in originals.items(): self.assertEqual(path.read_bytes(), content)

    def test_native_rejects_mismatched_direct_payload_before_msbuild(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); plan = root/'plan'; plan.mkdir()
            (plan/'payload.json').write_text(json.dumps({'A.cs': hashlib.sha256(b'expected').hexdigest()}))
            source = root/'A.cs'; source.write_bytes(b'changed')
            request = root/'request.json'
            request.write_text(json.dumps(dict(entry='App.csproj', output=str(root/'output'), diagnostics=str(root/'diagnostics'), manifest=str(plan/'manifest.json'), restore=str(plan/'restore.json'), sources=[dict(source=str(source), destination='A.cs')], seeds=[], preparedPlan=str(plan))))
            command = [str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'), str(ROOT/'tools/NativeProjectCache/bin/Release/net10.0/NativeProjectCache.dll'), '--portable-request', str(request)]
            p = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('Prepared payload differs from declared input', p.stderr)
            self.assertFalse((root/'diagnostics/action.json').exists())
