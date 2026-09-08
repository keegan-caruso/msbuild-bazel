"""Restore snapshots follow reference roles without dropping build dependencies."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from probe_generator_roles import Probe, PROJECT, PROJECTS, DOTNET_ROOT, edit


class ReferenceRoleRestore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bootstrap = Probe(Path(tempfile.mkdtemp(prefix='generator-role-restore-')) / 'bootstrap')
        print('Reference-role restore evidence: ' + str(cls.bootstrap.output.parent), flush=True)
        cls.bootstrap.run('exporter-build', [DOTNET_ROOT / 'dotnet', 'build', ROOT / 'tools/GraphExport',
            '-c', 'Release', '--nologo'], ROOT)

    def setUp(self):
        self.probe = Probe(self.bootstrap.output.parent / self._testMethodName)
        self.probe.copy(self.probe.source)
        self.probe.restore(self.probe.source, 'initial')

    def export(self, name, error=None):
        path, result = self.probe.export(self.probe.source, name, success=error is None)
        if error:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(error, result.stdout)
            self.assertFalse(path.exists(), 'rejected export published a manifest')
            return None
        return json.loads(path.read_text())

    def test_restore_graph_excludes_roles_but_scheduling_graph_keeps_them(self):
        source = self.probe.source
        saved = json.loads((source / 'App/obj/App.csproj.nuget.dgspec.json').read_text())
        self.assertEqual({Path(path).stem for path in saved['projects']}, {'App', 'Shared'})
        app = saved['projects'][str(source / PROJECT)]
        refs = app['restore']['frameworks']['net10.0']['projectReferences']
        self.assertEqual({Path(path).stem for path in refs}, {'Shared'})
        graph = self.export('accepted')
        nodes = {Path(node['project']).stem: node for node in graph['nodes']}
        self.assertEqual(set(nodes), PROJECTS)
        self.assertEqual(set(nodes['App']['dependencies']), {node['id'] for name, node in nodes.items() if name != 'App'})
        self.assertFalse(list(source.glob('*/bin/**/*.dll')), 'export compiled a producer')

    def test_ordinary_to_build_order_role_requires_fresh_consumer_restore(self):
        edit(self.probe.source / PROJECT, '<ProjectReference Include="../Shared/Shared.csproj" />',
             '<ProjectReference Include="../Shared/Shared.csproj" ReferenceOutputAssembly="false" />')
        self.export('stale', 'stale-restore: direct project reference set differs from restore')
        self.probe.restore(self.probe.source, 'refreshed')
        self.export('refreshed')

    def test_build_order_to_ordinary_role_requires_fresh_consumer_restore(self):
        path = self.probe.source / PROJECT
        edit(path, 'Include="../OrderOnly/OrderOnly.csproj"\n                      ReferenceOutputAssembly="false"',
             'Include="../OrderOnly/OrderOnly.csproj"\n                      ReferenceOutputAssembly="true"')
        self.export('stale', 'stale-restore: direct project reference set differs from restore')
        self.probe.restore(self.probe.source, 'refreshed')
        self.export('refreshed')

    def test_analyzer_producer_own_restore_is_still_required(self):
        cache = self.probe.source / 'ClassicGenerator/obj/project.nuget.cache'
        payload = json.loads(cache.read_text())
        payload['success'] = False
        cache.write_text(json.dumps(payload))
        self.export('failed-producer', 'stale-restore: latest restore did not succeed')
        self.probe.restore(self.probe.source, 'refreshed')
        self.export('refreshed')
        snapshot = self.probe.source / 'ClassicGenerator/obj/ClassicGenerator.csproj.nuget.dgspec.json'
        snapshot.unlink()
        self.export('missing-producer', 'stale-restore: consumer dependency restore snapshot missing')

    def test_analyzer_producer_cannot_use_stale_ordinary_child_snapshot(self):
        source = self.probe.source
        # App's restore closure excludes ClassicGenerator. ClassicGenerator's own
        # snapshot must still validate its ordinary Shared dependency recursively.
        edit(source / PROJECT, '<ProjectReference Include="../Shared/Shared.csproj" />', '')
        edit(source / 'ClassicGenerator/ClassicGenerator.csproj', '</Project>',
             '<ItemGroup><ProjectReference Include="../Shared/Shared.csproj" /></ItemGroup></Project>')
        self.probe.restore(source, 'with-child')
        self.export('with-child')
        (source / 'Shared/Shared.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><ItemGroup>'
            '<ProjectReference Include="../OrderOnly/OrderOnly.csproj" /></ItemGroup></Project>')
        self.probe.run('partial-child-restore', [DOTNET_ROOT / 'dotnet', 'msbuild', 'Shared/Shared.csproj',
            '-t:Restore', '-p:Configuration=Release', '-nodeReuse:false', '-nologo'], source)
        self.export('stale-child', 'stale-restore: direct project reference set differs from restore')
        self.probe.restore(source, 'refreshed')
        self.export('refreshed')

    def test_duplicate_project_with_conflicting_reference_roles_is_rejected(self):
        edit(self.probe.source / PROJECT, '</Project>',
             '<ItemGroup><ProjectReference Include="../ClassicGenerator/ClassicGenerator.csproj" /></ItemGroup></Project>')
        self.probe.restore(self.probe.source, 'conflict')
        self.export('conflict', 'unsupported-configured-reference: SDK reference negotiation is missing or ambiguous')

    def test_unqualified_output_item_type_is_rejected(self):
        path = self.probe.source / PROJECT
        contents = path.read_text()
        path.write_text(contents.replace('OutputItemType="Analyzer"', 'OutputItemType="Content"', 1))
        self.export('unqualified-role', 'unsupported-project-reference-role: only Analyzer')


if __name__ == '__main__':
    unittest.main()
