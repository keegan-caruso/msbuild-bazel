"""Runtime resolution keeps the application's selected package, rejects other collisions."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT/'.tools/dotnet'))


class RuntimePackages(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        (cls.root/'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup></Project>')
        (cls.root/'Program.cs').write_text('System.Console.WriteLine(System.IO.File.Exists("System.Numerics.Vectors.dll") ? "framework-staged" : "runtime-ok");')
        p = subprocess.run([str(SDK/'dotnet'), 'build', str(cls.root/'App.csproj'), '-c', 'Release', '-p:NuGetAudit=false'], capture_output=True, text=True)
        assert p.returncode == 0, p.stdout+p.stderr

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def launch(self, entry_package, dependency_package, same=False, missing=False, unsafe=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(self.root/'bin/Release/net10.0', root/'entry')
            (root/'dependency').mkdir()
            inputs=[]
            for name, package, payload in [('entry', entry_package, b'new'), ('dependency', dependency_package, b'new' if same else b'old')]:
                sources={}
                if package:
                    directory=root/'packages'/name;directory.mkdir(parents=True)
                    (directory/'Package.dll').write_bytes(payload)
                    sources['Package.dll']=dict(id=package,version=name,path='../escape' if unsafe else 'Package.dll')
                    inputs.append(dict(id=package,version=name,directory='packages/'+name))
                else:
                    (root/name/'Package.dll').write_bytes(payload)
                (root/name/'.rules-msbuild-package-files.json').write_text(json.dumps(sources))
                (root/name/'.rules-msbuild-packages.json').write_text(json.dumps({'Package.dll': package} if package else {}))
            (root/'launch.json').write_text(json.dumps(dict(entry='entry', dependencies=['dependency'], assembly='App', test=False, data=[], packages=[] if missing else inputs)))
            return subprocess.run([str(SDK/'dotnet'), str(ROOT/'tools/ExplicitBuild/bin/Release/net10.0/ExplicitBuild.dll'), 'run', str(root/'launch.json')], env=dict(os.environ, RULES_MSBUILD_RUNFILES=str(root)), capture_output=True, text=True)

    def test_application_package_version_wins(self):
        result = self.launch('Package', 'package')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('runtime-ok', result.stdout)

    def test_project_collision_is_rejected(self):
        for entry, dependency in [(None, 'Package'), ('Package', None), (None, None), ('Different', 'Package')]:
            with self.subTest(entry=entry, dependency=dependency):
                result = self.launch(entry, dependency)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Conflicting runtime/input destination', result.stderr)

    def test_identical_project_copy_is_allowed(self):
        result = self.launch(None, None, same=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_undeclared_runtime_package_is_rejected(self):
        result = self.launch('Package', 'package', missing=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Undeclared runtime package', result.stderr)

    def test_package_path_escape_is_rejected(self):
        result = self.launch('Package', 'package', unsafe=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsafe logical path', result.stderr)

    def test_framework_suppresses_only_older_inherited_package_assemblies(self):
        assembly = next((SDK/'shared/Microsoft.NETCore.App').glob('10.*/System.Numerics.Vectors.dll'))
        for version, package, expected in [('11.0.0.0', True, 'runtime-ok'), ('10.0.0.0', True, 'framework-staged'), ('9.0.0.0', True, 'framework-staged'), ('11.0.0.0', False, 'framework-staged')]:
            with self.subTest(version=version, package=package), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                shutil.copytree(self.root/'bin/Release/net10.0', root/'entry')
                (root/'dependency').mkdir()
                for name in ['entry', 'dependency']:
                    (root/name/'.rules-msbuild-packages.json').write_text('{}')
                    (root/name/'.rules-msbuild-package-files.json').write_text('{}')
                (root/'entry/.rules-msbuild-framework-files.json').write_text(json.dumps({'System.Numerics.Vectors.dll': version}))
                packages = []
                if package:
                    (root/'package').mkdir()
                    shutil.copyfile(assembly, root/'package/System.Numerics.Vectors.dll')
                    (root/'dependency/.rules-msbuild-packages.json').write_text(json.dumps({'System.Numerics.Vectors.dll': 'Vectors'}))
                    (root/'dependency/.rules-msbuild-package-files.json').write_text(json.dumps({'System.Numerics.Vectors.dll': dict(id='Vectors', version='1.0.0', path='System.Numerics.Vectors.dll')}))
                    packages.append(dict(id='Vectors', version='1.0.0', directory='package'))
                else:
                    shutil.copyfile(assembly, root/'dependency/System.Numerics.Vectors.dll')
                (root/'launch.json').write_text(json.dumps(dict(entry='entry', dependencies=['dependency'], assembly='App', test=False, data=[], packages=packages)))
                result = subprocess.run([str(SDK/'dotnet'), str(ROOT/'tools/ExplicitBuild/bin/Release/net10.0/ExplicitBuild.dll'), 'run', str(root/'launch.json')], env=dict(os.environ, RULES_MSBUILD_RUNFILES=str(root)), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), expected)
