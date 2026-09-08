"""Exercise the actual C# Git discovery boundary without running MSBuild graphs."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from prepare_graph import DOTNET_ROOT, ROOT


class GitInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.home = Path(cls.temporary.name).resolve()
        shutil.copy2(ROOT / 'tools/GraphExport/GitInputs.cs', cls.home / 'GitInputs.cs')
        (cls.home / 'Test.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings></PropertyGroup></Project>')
        (cls.home / 'Program.cs').write_text('''try { Console.WriteLine(string.Join("\\n", GitInputs.Discover(args[0]))); }
catch (Exception error) { Console.Error.WriteLine(error.Message); Environment.ExitCode = 1; }
class ExportException(string code, string message) : Exception(code + ":" + message) {}
''')
        result = subprocess.run([str(DOTNET_ROOT / 'dotnet'), 'build', '-c', 'Release', '--nologo'], cwd=cls.home,
                                text=True, capture_output=True, env=dict(os.environ, DOTNET_CLI_HOME=str(cls.home / 'home')))
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name).resolve()
        self.git = self.source / '.git'
        self.git.mkdir()
        for name, value in {'HEAD': 'abc', 'index': 'index', 'config': '[core]\n repositoryformatversion = 0\n[remote "origin"]\n url = https://github.com/example/repo.git\n'}.items():
            (self.git / name).write_text(value)

    def run_discovery(self, accepted):
        result = subprocess.run([str(DOTNET_ROOT / 'dotnet'), str(self.home / 'bin/Release/net10.0/Test.dll'), str(self.source)], text=True, capture_output=True)
        self.assertEqual(0 if accepted else 1, result.returncode, result.stdout + result.stderr)
        if not accepted: self.assertIn('unsupported-git-input:', result.stderr)
        return result.stdout

    def test_declares_origin_index_shallow_objects_and_refs(self):
        for name in ('shallow', 'objects/pack/p.pack', 'refs/tags/v1'):
            path = self.git / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(name)
        value = self.run_discovery(True)
        for name in ('config', 'index', 'shallow', 'objects/pack/p.pack', 'refs/tags/v1'):
            self.assertIn(str(self.git / name), value)

    def test_config_indirection_rejected(self):
        baseline = (self.git / 'config').read_text()
        for addition in ('[include]\n path = /external/config\n', '[includeIf "gitdir:*"]\n path = /external/config\n',
                         '[core]\n worktree = /external/source\n', '[extensions]\n worktreeConfig = true\n',
                         '[extensions]\n refStorage = reftable\n'):
            (self.git / 'config').write_text(baseline + addition)
            self.run_discovery(False)

    def test_external_layouts_rejected(self):
        for name in ('commondir', 'objects/info/alternates', 'sharedindex.abc'):
            path = self.git / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('/external')
            self.run_discovery(False)
            path.unlink()

    def test_symlink_directory_and_file_rejected(self):
        external = self.source / 'external'
        external.mkdir()
        for name in ('objects', 'refs', 'info'):
            (external / 'data').write_text('data')
            (external / 'exclude').write_text('exclude')
            link = self.git / name
            link.symlink_to(external, target_is_directory=True)
            self.run_discovery(False)
            link.unlink()
        (self.git / 'HEAD').unlink()
        (self.git / 'HEAD').symlink_to(external / 'data')
        self.run_discovery(False)

    def test_dangling_commondir_rejected(self):
        (self.git / 'commondir').symlink_to(self.source / 'missing-common-directory')
        self.run_discovery(False)

    def test_symlink_git_root_rejected(self):
        moved = self.source / 'external'
        self.git.rename(moved)
        self.git.symlink_to(moved, target_is_directory=True)
        self.run_discovery(False)
