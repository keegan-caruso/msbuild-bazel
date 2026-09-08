"""Reject stale package-reference semantics before graph/plan publication."""
import json
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from binary_inputs import Packages
from graph_private_assets import configure, write_fixture
from prepare_graph import DOTNET_ROOT, prepare


class PackageRestoreSemantics(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix='graph-restore-semantics-')).resolve()
        def run(name, command, cwd):
            result = subprocess.run(list(map(str, command)), cwd=cwd,
                env=dict(os.environ, DOTNET_CLI_HOME=str(cls.root / 'bootstrap-home'),
                         NUGET_PACKAGES=str(cls.root / 'bootstrap-packages'), MSBUILDDISABLENODEREUSE='1'),
                capture_output=True, text=True, timeout=180)
            (cls.root / (name + '.log')).write_text(result.stdout + result.stderr)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)
        cls.packages = Packages(cls.root / 'package-build', DOTNET_ROOT / 'dotnet', run)
        run('exporter-build', [DOTNET_ROOT / 'dotnet', 'build', ROOT / 'tools/GraphExport', '-c', 'Release', '--nologo'], ROOT)

    def setUp(self):
        self.evidence = self.root / self._testMethodName
        self.workspace = self.evidence / 'source'
        write_fixture(self.workspace)
        self.packages.feed(self.workspace / '.feed')
        configure(self.workspace, self.workspace / '.feed')
        self.project = self.workspace / 'src/Left/Left.csproj'
        self.serial = 0
        self.environment = dict(os.environ, DOTNET_CLI_HOME=str(self.workspace / '.dotnet-home'),
            NUGET_PACKAGES=str(self.workspace / '.nuget/packages'), MSBUILDDISABLENODEREUSE='1')
        environment = patch.dict(os.environ, self.environment)
        environment.start()
        self.addCleanup(environment.stop)

    def run_dotnet(self, label, args, error=None):
        result = subprocess.run([str(DOTNET_ROOT / 'dotnet'), *map(str, args)], cwd=self.workspace,
            env=self.environment, capture_output=True, text=True, timeout=180)
        (self.evidence / (label + '.log')).write_text(result.stdout + result.stderr)
        if error:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(error, result.stdout + result.stderr)
        else:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def restore(self):
        self.run_dotnet('restore', ['msbuild', 'build.proj', '-t:Restore', '-p:Configuration=Release', '-nodeReuse:false', '-nologo'])

    def export(self, error=None):
        self.serial += 1
        output = self.evidence / f'graph-{self.serial}.json'
        request = self.evidence / f'request-{self.serial}.json'
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(self.workspace),
            dotnetRoot=str(DOTNET_ROOT), sdkVersion='10.0.400', packageRoot=str(self.workspace / '.nuget/packages'),
            entryPoints=[dict(project='build.proj', globalProperties={'Configuration':'Release'})], output=str(output))))
        self.run_dotnet('export-' + str(self.serial), [ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], error)
        if error:
            self.assertFalse(output.exists(), 'failed export published a manifest')
        return output

    def assert_rejected_old_and_fresh(self, old):
        with self.assertRaisesRegex(ValueError, 'stale-restore'):
            prepare(self.workspace, old, self.evidence / 'rejected')
        self.assertFalse((self.evidence / 'rejected').exists())
        self.export(error='stale-restore')

    def assert_current_prepares(self, app_packages):
        manifest = self.export()
        graph = prepare(self.workspace, manifest, self.evidence / ('accepted-' + str(self.serial)))
        app = next(n['id'] for n in graph['nodes'] if n['project'].endswith('/App.csproj'))
        packages = json.loads((self.evidence / ('accepted-' + str(self.serial)) / 'package-manifests' / (app + '.json')).read_text())
        self.assertEqual(sorted(p['id'] for p in packages['packages']), app_packages)

    @staticmethod
    def plan_digest(path):
        return {item.relative_to(path).as_posix(): hashlib.sha256(item.read_bytes()).hexdigest()
                for item in path.rglob('*') if item.is_file()}

    def partial_restore_control(self, mutation, expected_packages):
        self.restore()
        original = self.export()
        plan = self.evidence / 'original-plan'
        prepare(self.workspace, original, plan)
        before = self.plan_digest(plan)
        mutation()
        self.run_dotnet('left-only-restore', ['msbuild', 'src/Left/Left.csproj', '-t:Restore',
            '-p:Configuration=Release', '-nodeReuse:false', '-nologo'])
        self.export(error='stale-restore')
        with self.assertRaisesRegex(ValueError, 'stale-(restore|manifest)'):
            prepare(self.workspace, original, self.evidence / 'rejected-plan')
        self.assertFalse((self.evidence / 'rejected-plan').exists())
        self.assertEqual(self.plan_digest(plan), before)
        self.restore()
        self.assert_current_prepares(expected_packages)

    def test_consumer_snapshot_rejects_partial_private_assets_restore(self):
        self.partial_restore_control(lambda: configure(self.workspace, self.workspace / '.feed',
            private_assets='all'), [])

    def test_consumer_snapshot_rejects_partial_version_restore(self):
        self.partial_restore_control(lambda: configure(self.workspace, self.workspace / '.feed',
            version='1.0.1'), ['RulesMsbuild.Binary', 'RulesMsbuild.Leaf'])

    def test_consumer_snapshot_rejects_removed_package_after_partial_restore(self):
        def remove():
            self.project.write_text('<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><ProjectReference Include="../Shared/Shared.csproj"/></ItemGroup></Project>')
            (self.project.parent / 'Value.cs').write_text('namespace Left; public static class Value { public static string Text => Shared.Message.Value; }')
        self.partial_restore_control(remove, [])

    def test_removed_project_edge_requires_consumer_restore(self):
        self.restore()
        original = self.export()
        plan = self.evidence / 'original-plan'
        prepare(self.workspace, original, plan)
        before = self.plan_digest(plan)
        app = self.workspace / 'src/App/App.csproj'
        app.write_text(app.read_text().replace('<ProjectReference Include="../Left/Left.csproj"/>', ''))
        (app.parent / 'Program.cs').write_text('System.Console.WriteLine(Right.Value.Text);')
        self.export(error='stale-restore')
        self.assertEqual(self.plan_digest(plan), before)
        self.restore()
        self.assert_current_prepares([])

    def test_consumer_direct_version_can_differ_from_dependency_resolution(self):
        app = self.workspace / 'src/App/App.csproj'
        app.write_text(app.read_text().replace('</Project>',
            '<ItemGroup><PackageReference Include="RulesMsbuild.Binary" Version="[1.0.1]"/></ItemGroup></Project>'))
        self.restore()
        def binary_versions(project):
            assets = json.loads((self.workspace / 'src' / project / 'obj/project.assets.json').read_text())
            return sorted(name for name in assets['libraries'] if name.startswith('RulesMsbuild.Binary/'))
        self.assertEqual(binary_versions('Left'), ['RulesMsbuild.Binary/1.0.0'])
        self.assertEqual(binary_versions('App'), ['RulesMsbuild.Binary/1.0.1'])
        self.assert_current_prepares(['RulesMsbuild.Binary', 'RulesMsbuild.Leaf'])

    def test_failed_restore_cannot_refresh_snapshot_over_invalid_assets(self):
        app = self.workspace / 'src/App/App.csproj'
        app.write_text(app.read_text().replace('</Project>',
            '<ItemGroup><PackageReference Include="RulesMsbuild.Binary" Version="[1.0.0]"/></ItemGroup></Project>'))
        self.restore()
        original = self.export()
        plan = self.evidence / 'original-plan'
        prepare(self.workspace, original, plan)
        before = self.plan_digest(plan)
        configure(self.workspace, self.workspace / '.feed', version='1.0.1')
        self.run_dotnet('left-only-restore', ['msbuild', 'src/Left/Left.csproj', '-t:Restore',
            '-p:Configuration=Release', '-nodeReuse:false', '-nologo'])
        self.run_dotnet('failed-whole-restore', ['msbuild', 'build.proj', '-t:Restore',
            '-p:Configuration=Release', '-nodeReuse:false', '-nologo'], error='NU1605')
        cache = json.loads((app.parent / 'obj/project.nuget.cache').read_text())
        self.assertFalse(cache['success'])
        self.export(error='stale-restore')
        self.assertEqual(self.plan_digest(plan), before)
        app.write_text(app.read_text().replace('[1.0.0]', '[1.0.1]'))
        self.restore()
        self.assert_current_prepares(['RulesMsbuild.Binary', 'RulesMsbuild.Leaf'])

    def test_missing_consumer_dependency_snapshot_rejects(self):
        self.restore()
        (self.workspace / 'src/App/obj/App.csproj.nuget.dgspec.json').unlink()
        self.export(error='stale-restore')

    def test_namespaced_exact_version_change_requires_restore(self):
        self.project.write_text(self.project.read_text().replace('<Project ', '<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003" ', 1))
        self.restore()
        old = self.export()
        self.project.write_text(self.project.read_text().replace('[1.0.0]', '[1.0.1]'))
        self.assert_rejected_old_and_fresh(old)
        self.restore()
        self.assert_current_prepares(['RulesMsbuild.Binary', 'RulesMsbuild.Leaf'])

    def test_direct_private_assets_change_requires_restore(self):
        self.restore()
        old = self.export()
        configure(self.workspace, self.workspace / '.feed', private_assets='all')
        self.assert_rejected_old_and_fresh(old)
        self.restore()
        self.assert_current_prepares([])

    def test_imported_private_assets_change_requires_restore(self):
        self.project.write_text(self.project.read_text().replace('Include="RulesMsbuild.Binary"', 'Include="RulesMsbuild.Binary" PrivateAssets="$(ScopedPrivacy)"'))
        props = self.workspace / 'Directory.Build.props'
        props.write_text(props.read_text().replace('</PropertyGroup>', '<ScopedPrivacy>none</ScopedPrivacy></PropertyGroup>'))
        self.restore()
        self.export()
        props.write_text(props.read_text().replace('<ScopedPrivacy>none</ScopedPrivacy>', '<ScopedPrivacy>all</ScopedPrivacy>'))
        self.export(error='stale-restore')
        self.restore()
        self.assert_current_prepares([])

    def test_removed_direct_reference_requires_restore(self):
        self.restore()
        self.project.write_text('<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><ProjectReference Include="../Shared/Shared.csproj"/></ItemGroup></Project>')
        self.export(error='stale-restore')

    def test_nondefault_asset_filters_reject_explicitly(self):
        configure(self.workspace, self.workspace / '.feed')
        self.project.write_text(self.project.read_text().replace('Include="RulesMsbuild.Binary"', 'Include="RulesMsbuild.Binary" IncludeAssets="compile"'))
        self.restore()
        self.export(error='unsupported-package')


if __name__ == '__main__':
    unittest.main()
