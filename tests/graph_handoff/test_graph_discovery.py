"""C14 fresh evaluation and C08 preparation publication controls."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests/graph'))
import prepare_graph
from prepare_graph import DOTNET_ROOT, prepare
from test_export_graph import write_fixture
from probe_bazel import json_stream
from probe_graph_execution import BAZEL


class GraphDiscoveryAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([str(DOTNET_ROOT / 'dotnet'), 'build', str(ROOT / 'tools/GraphExport'), '-c', 'Release', '--nologo'], text=True, capture_output=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='graph-discovery-')).resolve()
        self.workspace = self.root / 'source'
        write_fixture(self.workspace)
        (self.workspace / '.nuget/packages').mkdir(parents=True)
        self.serial = 0
        self.environment = dict(os.environ,
            NUGET_PACKAGES=str(self.workspace / '.nuget/packages'),
            DOTNET_CLI_HOME=str(self.workspace / '.dotnet-home'),
            MSBUILDDISABLENODEREUSE='1')
        # prepare() also launches exporter/adapter children. Keep those under the
        # same home as explicit restore/export and avoid workers from other tests.
        environment = patch.dict(os.environ, self.environment)
        environment.start()
        self.addCleanup(environment.stop)

    def run_dotnet(self, name, args):
        result = subprocess.run([str(DOTNET_ROOT / 'dotnet'), *map(str, args)], cwd=self.workspace, env=self.environment, capture_output=True, text=True, timeout=180)
        (self.root / (name + '.log')).write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def restore(self):
        self.run_dotnet('restore', ['msbuild', 'build.proj', '-t:Restore', '-p:Configuration=Release', '-nodeReuse:false', '-nologo'])

    def export(self, entries=None):
        self.serial += 1
        manifest = self.root / f'manifest-{self.serial}.json'
        request = self.root / f'request-{self.serial}.json'
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(self.workspace), dotnetRoot=str(DOTNET_ROOT), sdkVersion='10.0.100', packageRoot=str(self.workspace / '.nuget/packages'), entryPoints=entries or [dict(project='build.proj', globalProperties={'Configuration':'Release'})], output=str(manifest))))
        self.run_dotnet('export-' + str(self.serial), [ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request])
        return manifest

    def build(self, directory, graph, name):
        strategy = 'darwin-sandbox' if platform.system() == 'Darwin' else 'linux-sandbox'
        execution = self.root / (name + '-execution.json')
        result = subprocess.run([str(BAZEL), '--batch', '--nohome_rc', '--noworkspace_rc',
            '--output_base=' + str(self.root / (name + '-base')),
            '--output_user_root=' + str(self.root / 'bazel-user'), 'build', '//:all',
            '--disk_cache=' + str(self.root / 'disk-cache'), '--spawn_strategy=' + strategy,
            '--strategy=MsbuildProject=' + strategy, '--jobs=2', '--noshow_progress',
            '--execution_log_json_file=' + str(execution)], cwd=directory,
            capture_output=True, text=True, timeout=180, env=self.environment)
        (self.root / (name + '-build.log')).write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        nodes = {n['id']: n['project'] for n in graph['nodes']}
        actions = [r for r in json_stream(execution) if r.get('mnemonic') == 'MsbuildProject']
        executed = set()
        for record in actions:
            if record.get('cacheHit', False):
                continue
            self.assertEqual(record.get('runner'), strategy)
            identity = record['targetLabel'].split(':node_')[-1]
            action = json.loads((directory / f'bazel-bin/node_{identity}.diagnostics/action.json').read_text())
            self.assertEqual(action['compiledProjects'], [Path(nodes[identity]).stem])
            executed.add(nodes[identity])
        return executed

    def baseline(self):
        old = self.export()
        graph = prepare(self.workspace, old, self.root / 'baseline')
        self.assertEqual(self.build(self.root / 'baseline', graph, 'baseline'), {n['project'] for n in graph['nodes']})
        return old

    def stale_then_regenerate(self, old, expected, expected_error='stale graph discovery'):
        with self.assertRaisesRegex(ValueError, expected_error):
            prepare(self.workspace, old, self.root / 'rejected')
        self.assertFalse((self.root / 'rejected').exists())
        self.restore()
        fresh = self.export()
        graph = prepare(self.workspace, fresh, self.root / 'accepted')
        self.assertNotEqual(json.loads(old.read_text()), graph)
        executed = self.build(self.root / 'accepted', graph, 'regenerated')
        self.assertEqual(executed, {'workspace/src/' + n + '/' + n + '.csproj' for n in expected})
        (self.root / 'report.json').write_text(json.dumps(dict(schemaVersion=1,
            before=json.loads(old.read_text()), after=graph, executedProjects=sorted(executed)), indent=2))
        return graph

    def test_equivalent_entry_requests_are_canonical_and_revalidate(self):
        self.restore()
        first = self.export(entries=[
            dict(project='./src/Right/Right.csproj', globalProperties={
                'RestorePackagesPath': str(self.root / 'ignored-first'),
                'Configuration': 'Release', 'BazelGraphExport': 'false',
                'CustomAfterMicrosoftCommonTargets': str(self.root / 'ignored-first.targets')}),
            dict(project='src/Left/../Left/Left.csproj', globalProperties={'Configuration': 'Release'})])
        second = self.export(entries=[
            dict(project='src/Left/Left.csproj', globalProperties={'Configuration': 'Release'}),
            dict(project='src/Right/Right.csproj', globalProperties={
                'Configuration': 'Release', 'restorepackagespath': str(self.root / 'ignored-second'),
                'bazelgraphexport': 'true',
                'customaftermicrosoftcommontargets': str(self.root / 'ignored-second.targets')})])
        self.assertEqual(first.read_bytes(), second.read_bytes())
        graph = json.loads(second.read_text())
        self.assertEqual(graph['entryRequests'], [
            dict(project='src/Left/Left.csproj', globalProperties={'Configuration': 'Release'}),
            dict(project='src/Right/Right.csproj', globalProperties={'Configuration': 'Release'})])
        self.assertNotIn('ignored-', second.read_text())
        self.assertEqual(prepare(self.workspace, second, self.root / 'canonical'), graph)

    def test_semantic_entry_properties_remain_distinct(self):
        self.restore()
        graphs = []
        for value in ('first', 'second'):
            manifest = self.export(entries=[dict(project='src/Shared/Shared.csproj',
                globalProperties={'Configuration': 'Release', 'DiscoveryFlavor': value})])
            reordered = self.export(entries=[dict(project='src/Shared/Shared.csproj',
                globalProperties={'DiscoveryFlavor': value, 'Configuration': 'Release'})])
            self.assertEqual(manifest.read_bytes(), reordered.read_bytes())
            graph = json.loads(manifest.read_text())
            self.assertEqual(graph['entryRequests'][0]['globalProperties']['DiscoveryFlavor'], value)
            self.assertEqual(graph['nodes'][0]['globalProperties']['discoveryflavor'], value)
            graphs.append(graph)
        self.assertNotEqual(graphs[0]['nodes'][0]['id'], graphs[1]['nodes'][0]['id'])

    def test_new_globbed_source(self):
        self.restore()
        old = self.baseline()
        (self.workspace / 'src/App/Added.cs').write_text('class Added {}')
        graph = self.stale_then_regenerate(old, {'App'})
        app = next(n for n in graph['nodes'] if n['project'].endswith('/App.csproj'))
        self.assertIn('workspace/src/App/Added.cs', [i['path'] for i in app['inputs']])
        self.assertTrue((self.root / 'accepted/src/src/App/Added.cs').is_file())

    def test_previously_absent_optional_import(self):
        project = self.workspace / 'src/App/App.csproj'
        project.write_text(project.read_text().replace('</Project>', '<Import Project="Optional.targets" Condition="Exists(\'Optional.targets\')"/></Project>'))
        self.restore()
        old = self.baseline()
        (project.parent / 'Optional.targets').write_text('<Project/>')
        graph = self.stale_then_regenerate(old, {'App'})
        app = next(n for n in graph['nodes'] if n['project'].endswith('/App.csproj'))
        self.assertIn('workspace/src/App/Optional.targets', [i['path'] for i in app['inputs']])

    def test_conditional_dependency_discovery(self):
        project = self.workspace / 'src/Left/Left.csproj'
        project.write_text(project.read_text().replace('Include="../Shared/Shared.csproj"', 'Include="../Shared/Shared.csproj" Condition="Exists(\'select-shared.flag\')"'))
        project.write_text(project.read_text().replace('</ItemGroup>', '<BazelExtraInput Include="select-shared.flag" Condition="Exists(\'select-shared.flag\')"/></ItemGroup>'))
        (project.parent / 'Value.cs').write_text('namespace Left; public static class Value { public static string Text => \"left\"; }')
        self.restore()
        old = self.baseline()
        (project.parent / 'select-shared.flag').write_text('selected')
        graph = self.stale_then_regenerate(old, {'Left', 'App'},
            expected_error='stale-restore: direct project reference set differs from restore:')
        before = next(n for n in json.loads(old.read_text())['nodes'] if n['project'].endswith('/Left.csproj'))
        after = next(n for n in graph['nodes'] if n['project'].endswith('/Left.csproj'))
        self.assertEqual(before['dependencies'], [])
        self.assertEqual(len(after['dependencies']), 1)

    def test_preparation_integrity_with_retained_cache(self):
        self.restore()
        manifest = self.baseline()
        source = self.workspace / 'src/App/Program.cs'
        original = source.read_text()
        source.unlink()
        with self.assertRaisesRegex(ValueError, 'missing or escaping input: workspace/src/App/Program.cs'):
            prepare(self.workspace, manifest, self.root / 'missing')
        source.write_text(original + '\n// stale recorded digest\n')
        with self.assertRaisesRegex(ValueError, 'stale graph input: workspace/src/App/Program.cs'):
            prepare(self.workspace, manifest, self.root / 'corrupt')
        self.assertFalse((self.root / 'missing').exists())
        self.assertFalse((self.root / 'corrupt').exists())
        self.assertTrue((self.root / 'disk-cache').is_dir())
        self.assertTrue((self.root / 'baseline/BUILD.bazel').is_file())

    def test_interrupted_publication_and_explicit_retry(self):
        self.restore()
        manifest = self.export()
        copy = shutil.copyfile
        def interrupted(source, destination, *args, **kwargs):
            result = copy(source, destination, *args, **kwargs)
            if str(destination).endswith('ReplayPlugin.dll'):
                raise KeyboardInterrupt('controlled interruption during payload copy')
            return result
        with patch.object(prepare_graph.shutil, 'copyfile', interrupted):
            with self.assertRaises(KeyboardInterrupt):
                prepare(self.workspace, manifest, self.root / 'generated')
        self.assertFalse((self.root / 'generated').exists())
        self.assertEqual(list(self.root.glob('.graph-prepare-*')), [])
        prepare(self.workspace, manifest, self.root / 'generated')
        self.assertTrue((self.root / 'generated/BUILD.bazel').is_file())

    def test_concurrent_preparations_do_not_collide(self):
        self.restore()
        manifest = self.export()
        with ThreadPoolExecutor(max_workers=2) as pool:
            graphs = list(pool.map(lambda name: prepare(self.workspace, manifest, self.root / name), ('first', 'second')))
        self.assertEqual(*graphs)
        for name in ('BUILD.bazel', 'graph.json', 'runner/ActionRunner.dll', 'ReplayPlugin.dll'):
            self.assertEqual((self.root / 'first' / name).read_bytes(), (self.root / 'second' / name).read_bytes())
        with self.assertRaises(FileExistsError):
            prepare(self.workspace, manifest, self.root / 'first')

if __name__ == '__main__':
    unittest.main()
