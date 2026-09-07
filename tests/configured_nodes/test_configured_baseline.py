"""Ordinary MSBuild baseline only; no generated-adapter acceptance claim."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT / '.tools/dotnet'))


class ConfiguredBaseline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = Path(tempfile.mkdtemp(prefix='configured-baseline-')).resolve()
        print('Configured baseline evidence: ' + str(cls.evidence), flush=True)
        cls.env = dict(os.environ, DOTNET_CLI_HOME=str(cls.evidence / 'home'),
                       NUGET_PACKAGES=str(cls.evidence / 'packages'),
                       MSBUILDDISABLENODEREUSE='1', DOTNET_CLI_TELEMETRY_OPTOUT='1')

    def command(self, workspace, name, *arguments, expect_success=True):
        result = subprocess.run([str(SDK / 'dotnet'), *arguments], cwd=workspace,
                                env=self.env, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, timeout=300)
        (workspace.parent / (name + '.log')).write_text(result.stdout)
        if expect_success:
            self.assertEqual(result.returncode, 0, result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stdout

    def fixture(self, name):
        workspace = self.evidence / name / 'workspace'
        shutil.copytree(ROOT / 'tests/fixtures/configured-nodes', workspace)
        return workspace

    def build(self, workspace, name, entry, *properties):
        return self.command(workspace, name, 'msbuild', entry, '-t:Build',
                            '-p:Configuration=Release', '-graphBuild', '-isolateProjects',
                            '-nodeReuse:false', '-nologo', *properties)

    def restore(self, workspace, entry, *properties):
        self.command(workspace, 'restore', 'msbuild', entry, '-t:Restore',
                     '-p:Configuration=Release', '-graphBuild', '-nodeReuse:false', '-nologo', *properties)

    def restore_variants(self, workspace):
        # NuGet restore collapses same-path projects; materialize both configured assets explicitly.
        for flavor in ('red', 'blue'):
            self.command(workspace, 'restore-' + flavor, 'msbuild', 'Shared/Shared.csproj',
                         '-t:Restore', '-p:Configuration=Release', '-p:Flavor=' + flavor,
                         '-nodeReuse:false', '-nologo')

    def test_default_transitive_reference_shape_rejects_isolated_build(self):
        workspace = self.fixture('default-transitive')
        props = workspace / 'Directory.Build.props'
        props.write_text(props.read_text().replace(
            '<DisableTransitiveProjectReferences>true</DisableTransitiveProjectReferences>', ''))
        self.restore(workspace, 'build.proj')
        # Ordinary restore does not materialize the red/blue configured assets.
        self.assertTrue(any(not (workspace / f'Shared/obj/{flavor}/project.assets.json').exists()
                            for flavor in ('red', 'blue')))
        self.restore_variants(workspace)
        log = self.command(workspace, 'isolated-build', 'msbuild', 'build.proj', '-t:Build',
            '-p:Configuration=Release', '-graphBuild', '-isolateProjects', '-nodeReuse:false',
            '-nologo', expect_success=False)
        self.assertIn('MSB4252', log)
        self.assertRegex(log, r'Static graph loaded[^\n]*: 7 nodes, 17 edges')
        self.assertIn('Shared/Shared.csproj', log)
        nonisolated = self.command(workspace, 'nonisolated-build', 'msbuild', 'build.proj',
            '-t:Build', '-p:Configuration=Release', '-graphBuild', '-nodeReuse:false', '-nologo')
        self.assertIn('R03_COMPILE:Shared|plain|net10.0', nonisolated)
        self.assertEqual(self.command(workspace, 'nonisolated-app',
            'App/bin/Release/net10.0/App.dll').strip(), 'red:common|blue:common')
        (workspace.parent / 'report.json').write_text(json.dumps(dict(
            scope='ordinary-msbuild-default-transitive-controls', diagnostic='MSB4252',
            nonisolatedOutput='red:common|blue:common', additionalDynamicNode='Shared|plain|net10.0'), indent=2))

    def test_same_path_variants_and_property_removal_converge(self):
        workspace = self.fixture('configured-edges')
        self.restore(workspace, 'build.proj')
        self.restore_variants(workspace)
        log = self.build(workspace, 'build', 'build.proj')
        self.assertRegex(log, r'Static graph loaded[^\n]*: 7 nodes, 7 edges')
        markers = [line.strip() for line in log.splitlines() if 'R03_COMPILE:' in line]
        expected = ['App|plain', 'Left|plain', 'Right|plain', 'Shared|red', 'Shared|blue', 'Common|plain']
        self.assertCountEqual(markers, ['R03_COMPILE:' + p + '|net10.0' for p in expected])
        output = self.command(workspace, 'app', 'App/bin/Release/net10.0/App.dll').strip()
        self.assertEqual(output, 'red:common|blue:common')
        for flavor in ('red', 'blue'):
            self.assertTrue((workspace / f'Shared/bin/{flavor}/Release/net10.0/Shared.{flavor}.dll').is_file())
        self.build(workspace, 'unchanged', 'build.proj')
        self.assertEqual(self.command(workspace, 'unchanged-app',
                         'App/bin/Release/net10.0/App.dll').strip(), output)
        (workspace.parent / 'report.json').write_text(json.dumps(dict(scope='ordinary-msbuild',
            output=output, compileMarkers=markers, commonCompilationCount=1), indent=2))

    def test_explicit_inner_framework_and_outer_graph(self):
        inner = self.fixture('inner')
        self.restore(inner, 'Multi/Multi.csproj', '-p:TargetFramework=net10.0')
        log = self.build(inner, 'build', 'Multi/Multi.csproj', '-p:TargetFramework=net10.0')
        self.assertIn('R03_COMPILE:Multi|plain|net10.0', log)
        self.assertNotIn('R03_OUTER:', log)
        self.assertFalse((inner / 'Multi/bin/Release/netstandard2.1/Multi.dll').exists())
        outer = self.fixture('outer')
        self.restore(outer, 'Multi/Multi.csproj')
        log = self.build(outer, 'build', 'Multi/Multi.csproj')
        for framework in ('net10.0', 'netstandard2.1'):
            self.assertEqual(log.count('R03_COMPILE:Multi|plain|' + framework), 1)
            self.assertTrue((outer / f'Multi/bin/Release/{framework}/Multi.dll').is_file())
        self.assertIn('R03_OUTER:Multi|net10.0;netstandard2.1', log)


if __name__ == '__main__':
    unittest.main()
