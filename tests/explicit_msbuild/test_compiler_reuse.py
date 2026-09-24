"""Keep compiler-server reuse tied to tools rather than consumer graph identity."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('runtime_compiler_reuse', Path(__file__).parent/'runtime/compiler_reuse.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CompilerReuse(unittest.TestCase):
    def setUp(self):
        self.key = 'Microsoft.Net.Compilers.Toolset/5.0.0'
        self.locked = {'microsoft.net.compilers.toolset': (self.key, {})}
        self.manifest = {self.key: {'sha256': 'a'*64}}

    def properties(self, sdk='10.0.400'):
        return module.compiler_properties(self.locked, self.manifest, sdk)

    def test_unrelated_dependencies_share_the_compiler(self):
        first = self.properties()
        self.locked['example.library'] = ('Example.Library/1.0.0', {})
        self.manifest['Example.Library/1.0.0'] = {'sha256': 'b'*64}
        self.assertEqual(first, self.properties())
        self.assertEqual(first['UseSharedCompilation'], 'true')

    def test_changed_tool_bytes_or_sdk_do_not_share_identity(self):
        original = self.properties()['SharedCompilationId']
        self.assertNotEqual(original, self.properties('10.0.401')['SharedCompilationId'])
        self.manifest[self.key]['sha256'] = 'b'*64
        self.assertNotEqual(original, self.properties()['SharedCompilationId'])

    def test_unlocked_compiler_is_rejected(self):
        self.manifest[self.key]['sha256'] = 'not-a-digest'
        with self.assertRaises(ValueError):
            self.properties()
        self.manifest.clear()
        with self.assertRaises(KeyError):
            self.properties()

    def test_sdk_compiler_keeps_its_default_pipe_identity(self):
        self.assertEqual(module.compiler_properties({}, {}, '10.0.400'), {'UseSharedCompilation': 'true'})


if __name__ == '__main__':
    unittest.main()
