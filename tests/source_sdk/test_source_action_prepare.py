"""Controls for source SDK qualification's generated Bazel declarations."""
import ast
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from source_action_prepare import write_bazel_files


class SourceActionTemplatesTests(unittest.TestCase):
    def test_generated_bazel_files_parse_and_keep_declared_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            rules = workspace / 'rules path "quoted"'
            write_bazel_files(workspace, rules)
            module = (workspace / 'MODULE.bazel').read_text()
            build = (workspace / 'BUILD.bazel').read_text()
            # These templates use the Python-compatible subset of Starlark.
            ast.parse(module, filename='MODULE.bazel')
            ast.parse(build, filename='BUILD.bazel')
            self.assertIn('path=' + json.dumps(str(rules)), module)
            self.assertIn('version="10.0.400"', module)
            for declaration in ('sources="sources.tar"', 'bootstrap="bootstrap.tar"',
                                'native_tools="native.tar"', 'name="smoke"'):
                self.assertIn(declaration, build)
            buildifier = os.environ.get('BUILDIFIER')
            if buildifier:
                for name in ('MODULE.bazel', 'BUILD.bazel'):
                    subprocess.run([buildifier, '-mode=fix', str(workspace / name)],
                                   stdout=subprocess.DEVNULL, check=True)


if __name__ == '__main__':
    unittest.main()
