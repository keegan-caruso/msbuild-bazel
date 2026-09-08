"""Native replay preserves implicit producer globals under an explicit parent TFM."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from probe_generator_roles import Probe, DOTNET_ROOT, PROJECT


class ExplicitFrameworkProbe(Probe):
    def export(self, source, name, success=True):
        request = self.output / (name + '-request.json')
        manifest = self.output / (name + '-manifest.json')
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(source),
            dotnetRoot=str(DOTNET_ROOT), sdkVersion='10.0.400', packageRoot=str(source / '.nuget/packages'),
            entryPoints=[dict(project=PROJECT, globalProperties={'Configuration': 'Release', 'TargetFramework': 'net10.0'})], output=str(manifest))))
        result = self.run(name + '-export', [DOTNET_ROOT / 'dotnet',
            ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], source, success)
        return manifest, result


class ExplicitFrameworkReplay(unittest.TestCase):
    def test_implicit_producers_replay_under_explicit_consumer_framework(self):
        output = Path(tempfile.mkdtemp(prefix='generator-explicit-framework-')) / 'probe'
        print('Explicit framework replay evidence: ' + str(output), flush=True)
        probe = ExplicitFrameworkProbe(output)
        probe.execute(cold_only=True)
        self.assertTrue(probe.report['accepted'])
        nodes = {Path(node['project']).stem: node for node in probe.graph['nodes']}
        self.assertEqual(nodes['App']['globalProperties']['targetframework'], 'net10.0')
        for name, node in nodes.items():
            if name != 'App':
                self.assertNotIn('targetframework', node['globalProperties'])
        # Probe.build also requires one compilation per action and complete,
        # strict replay hits for every dependency in the consumer action.


if __name__ == '__main__':
    unittest.main()
