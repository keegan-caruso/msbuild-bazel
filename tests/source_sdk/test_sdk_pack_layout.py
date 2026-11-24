"""Exercise SDK pack artifact declarations and the actual extraction command."""
import ast
import io
from pathlib import Path
import subprocess
import tarfile
import tempfile
from types import SimpleNamespace
import unittest


def layout(root, packs, native_aot, split_frameworks=False, sdk_version="", sdk_files=None, sdk_directories=None):
    """Run the Starlark implementation's Python-compatible body with action capture."""
    source = Path(__file__).with_name('source_action.bzl').read_text()
    node = next(node for node in ast.parse(source).body
                if isinstance(node, ast.FunctionDef) and node.name == '_sdk_layout')
    namespace = dict(depset=list, DefaultInfo=lambda **kw: kw, OutputGroupInfo=lambda **kw: kw,
                     fail=lambda message: (_ for _ in ()).throw(ValueError(message)))
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'source_action.bzl', 'exec'), namespace)
    calls = []
    def declare(name):
        path = root / name
        return SimpleNamespace(path=str(path), dirname=str(path.parent))
    ctx = SimpleNamespace(label=SimpleNamespace(name='layout'),
                          attr=SimpleNamespace(pack_names=packs, native_aot_packs=native_aot, split_frameworks=split_frameworks, packages={}, sdk_version=sdk_version, sdk_files=sdk_files or [], sdk_directories=sdk_directories or []),
                          file=SimpleNamespace(archive=declare('sdk.tar.gz')),
                          files=SimpleNamespace(packages=[]),
                          actions=SimpleNamespace(declare_file=declare, declare_directory=declare,
                                                  run_shell=lambda **kw: calls.append(kw)))
    return namespace['_sdk_layout'](ctx), calls[0]


class SdkPackLayoutTests(unittest.TestCase):
    def test_complete_default_and_selective_managed_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            full, _ = layout(root, [], [])
            self.assertIn(str(root / 'layout/packs'), [f.path for f in full[0]['files']])
            groups, _ = layout(root, ['Ref', 'Runtime', 'NativeAOT', 'ILCompiler'], ['NativeAOT', 'ILCompiler'])
            full = {f.path for f in groups[0]['files']}
            managed = {f.path for f in groups[1]['managed']}
            self.assertEqual(full - managed, {str(root / 'layout/packs/NativeAOT'), str(root / 'layout/packs/ILCompiler')})
            self.assertIn(str(root / 'layout/packs/Ref'), managed)
            self.assertIn(str(root / 'layout/packs/Runtime'), managed)
            self.assertNotIn(str(root / 'layout/packs'), full)

    def test_framework_and_pack_selections_compose(self):
        groups, _ = layout(Path('/tmp/control'), ['Ref', 'NativeAOT'], ['NativeAOT'], split_frameworks=True)
        core = {f.path for f in groups[1]['core_runtime']}
        self.assertEqual(core, {'/tmp/control/layout/dotnet', '/tmp/control/layout/host',
                                '/tmp/control/layout/shared/Microsoft.NETCore.App'})
        managed = {f.path for f in groups[1]['managed']}
        self.assertIn('/tmp/control/layout/shared/Microsoft.AspNetCore.App', managed)
        self.assertNotIn('/tmp/control/layout/packs/NativeAOT', managed)

    def test_invalid_pack_declarations_fail_analysis(self):
        for packs, excluded in [(['../bad'], []), (['two names'], []), (['wild*'], []), (['wild?'], []), (['wild[set]'], []), (['tab\tname'], []), (['Ref', 'Ref'], []), (['Ref'], ['missing'])]:
            with self.subTest(packs=packs, excluded=excluded), self.assertRaises(ValueError):
                layout(Path('/tmp/control'), packs, excluded)

    def test_actual_extraction_rejects_missing_or_undeclared_packs(self):
        for archived in [['Ref', 'ILCompiler'], ['Ref'], ['Ref', 'ILCompiler', 'NewPack'], ['Ref', 'ILCompiler', '.hidden'], ['Ref', 'ILCompiler', 'file:.hidden']]:
            with self.subTest(archived=archived), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, action = layout(root, ['Ref', 'ILCompiler'], ['ILCompiler'])
                with tarfile.open(root / 'sdk.tar.gz', 'w:gz') as archive:
                    for name in archived:
                        entry = tarfile.TarInfo('packs/' + (name[5:] if name.startswith('file:') else name + '/payload'))
                        entry.size = 7
                        archive.addfile(entry, io.BytesIO(b'payload'))
                result = subprocess.run(['bash', '-c', action['command'], '--', *action['arguments']],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, archived == ['Ref', 'ILCompiler'], result.stderr)
                self.assertEqual((root / 'layout/packs/Ref/payload').read_bytes(), b'payload')


    def test_legacy_layout_does_not_require_inventory_python(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _, action = layout(root, [], [])
            with tarfile.open(root / 'sdk.tar.gz', 'w:gz') as archive:
                entry = tarfile.TarInfo('packs/Ref/payload')
                entry.size = 7
                archive.addfile(entry, io.BytesIO(b'payload'))
            command = 'python3() { return 99; }\n' + action['command']
            result = subprocess.run(['bash', '-c', command, '--', *action['arguments']],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_framework_inventory_rejects_hidden_files_and_directories(self):
        for unexpected in ['', '.hidden', '.hidden/payload']:
            with self.subTest(unexpected=unexpected), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, action = layout(root, [], [], split_frameworks=True)
                names = ['shared/Microsoft.NETCore.App/payload', 'shared/Microsoft.AspNetCore.App/payload']
                if unexpected:
                    names.append('shared/' + unexpected)
                with tarfile.open(root / 'sdk.tar.gz', 'w:gz') as archive:
                    for name in names:
                        entry = tarfile.TarInfo(name)
                        entry.size = 7
                        archive.addfile(entry, io.BytesIO(b'payload'))
                result = subprocess.run(['bash', '-c', action['command'], '--', *action['arguments']],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, not unexpected, result.stderr)

class SdkCompilerLayoutTests(unittest.TestCase):
    def test_shared_outputs_keep_physical_paths_without_overlapping_trees(self):
        groups, action = layout(Path('/tmp/control'), ['Ref', 'AOT'], ['AOT'], True,
                                '11.0.100', ['.version', 'MSBuild.dll'], ['DotnetTools', 'FSharp', 'Roslyn'])
        full = {f.path for f in groups[0]['files']}
        managed = {f.path for f in groups[1]['managed']}
        self.assertEqual(full - managed, {'/tmp/control/layout/packs/AOT',
                         '/tmp/control/layout/sdk/11.0.100/DotnetTools',
                         '/tmp/control/layout/sdk/11.0.100/FSharp'})
        self.assertEqual(len(action['outputs']), len(full))
        for path in full:
            self.assertFalse(any(other.startswith(path + '/') for other in full), path)
        self.assertIn('/tmp/control/layout/sdk/11.0.100/MSBuild.dll', managed)
        self.assertIn('/tmp/control/layout/sdk/11.0.100/Roslyn', managed)

    def test_invalid_sdk_inventory_fails_analysis(self):
        for version, files, directories in [('', ['file'], []), ('11.0.100', [], []),
                ('../11', [], ['DotnetTools', 'FSharp']),
                ('11.0.100', ['bad/name'], ['DotnetTools', 'FSharp']),
                ('11.0.100', ['FSharp'], ['DotnetTools', 'FSharp']),
                ('11.0.100', [], ['DotnetTools'])]:
            with self.subTest(version=version, files=files, directories=directories), self.assertRaises(ValueError):
                layout(Path('/tmp/control'), [], [], sdk_version=version,
                       sdk_files=files, sdk_directories=directories)

    def test_actual_sdk_inventory_and_entry_types_are_checked(self):
        names = ['sdk/11.0.100/MSBuild.dll', 'sdk/11.0.100/.version',
                 'sdk/11.0.100/DotnetTools/payload', 'sdk/11.0.100/FSharp/payload',
                 'sdk/11.0.100/Roslyn/payload']
        for mutation in ['valid', 'missing', 'extra', 'version', 'file-directory', 'directory-file', 'symlink']:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                _, action = layout(root, [], [], sdk_version='11.0.100',
                                   sdk_files=['MSBuild.dll', '.version'],
                                   sdk_directories=['DotnetTools', 'FSharp', 'Roslyn'])
                archived = list(names)
                if mutation == 'missing': archived.remove(names[0])
                if mutation == 'extra': archived.append('sdk/11.0.100/.hidden')
                if mutation == 'version': archived.append('sdk/12.0.100/payload')
                if mutation == 'file-directory': archived[0] += '/payload'
                if mutation == 'directory-file': archived[2] = 'sdk/11.0.100/DotnetTools'
                with tarfile.open(root / 'sdk.tar.gz', 'w:gz') as archive:
                    for name in archived:
                        entry = tarfile.TarInfo(name)
                        if mutation == 'symlink' and name == names[0]:
                            entry.type = tarfile.SYMTYPE
                            entry.linkname = '.version'
                            archive.addfile(entry)
                        else:
                            entry.size = 7
                            archive.addfile(entry, io.BytesIO(b'payload'))
                result = subprocess.run(['bash', '-c', action['command'], '--', *action['arguments']],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode == 0, mutation == 'valid', result.stderr)
                if mutation == 'valid':
                    self.assertEqual((root / 'layout/sdk/11.0.100/DotnetTools/payload').read_bytes(), b'payload')
                    self.assertEqual((root / 'layout/sdk/11.0.100/FSharp/payload').read_bytes(), b'payload')

if __name__ == '__main__':
    unittest.main()
