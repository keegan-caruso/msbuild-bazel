"""R03 real native actions; no fixture report or cache-hit substitute for builds."""
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ConfiguredExecution(unittest.TestCase):
    def acceptance(self, scope, count, expected):
        output = Path(tempfile.mkdtemp(prefix='configured-execution-')) / 'probe'
        print('Configured execution evidence: ' + str(output), flush=True)
        result = subprocess.run([sys.executable, str(ROOT / 'tools/probe_configured_nodes.py'),
            '--output', str(output), '--scope', scope], cwd=ROOT, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1200)
        self.assertEqual(result.returncode, 0, result.stdout)
        report = json.loads((output / 'report.json').read_text())
        self.assertEqual(report['baselineOutput'], expected)
        for name, failure in report['failures'].items():
            self.assertNotEqual(failure['returncode'], 0)
            self.assertFalse(failure['publishedManifest'])
            diagnostic = 'unsupported-configuration' if name == 'outer' else 'unsupported-configured-transitive'
            self.assertIn(diagnostic, (output / failure['log']).read_text())
        cold = report['cases']['cold']
        self.assertTrue(cold['preparationWorkspaceAbsent'])
        self.assertEqual(len(cold['nodes']), count)
        self.assertEqual({a['nodeId'] for a in cold['actions'] if not a['cacheHit']}, set(cold['nodes']))
        for case in report['cases'].values():
            self.assertTrue((output / case['executionLog']).is_file())
            for action in case['actions']:
                self.assertFalse(action['remotable'])
                self.assertFalse(action['remoteCacheable'])
                if action['cacheHit']: continue
                self.assertIn(action['runner'], ('darwin-sandbox', 'linux-sandbox'))
                self.assertEqual(action['compiledProjects'], [Path(action['project']).stem])
                markers = re.findall(r'RULES_MSBUILD_COMPILE:([^\r\n]+)', (output / action['log']).read_text())
                self.assertEqual([m.strip() for m in markers], [action['project'].removeprefix('workspace/')])
                self.assertTrue((output / action['log']).is_file())
            canonical = {}
            for logical, item in case['bundleFiles'].items():
                path = output / item['file']
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), item['sha256'])
                self.assertEqual(bool(path.stat().st_mode & 0o111), item['executable'])
                canonical[logical] = {k: item[k] for k in ('sha256', 'executable')}
            self.assertEqual(hashlib.sha256(json.dumps(canonical, sort_keys=True,
                separators=(',', ':')).encode()).hexdigest(), case['bundleDigest'])
        self.assertEqual(report['cases']['unchanged']['output'], expected)
        self.assertFalse([a for a in report['cases']['unchanged']['actions'] if not a['cacheHit']])
        recovery = report['cases']['relocated']
        self.assertEqual(recovery['output'], expected)
        for field in ('outputBaseAbsentBeforeBuild', 'producerWorkspaceAbsent',
                      'preparationWorkspaceAbsent', 'outputsAbsentBeforeBuild'):
            self.assertTrue(recovery[field], field)
        self.assertEqual({a['nodeId'] for a in recovery['actions'] if a['cacheHit']}, set(cold['nodes']))
        self.assertFalse([a for a in recovery['actions'] if not a['cacheHit']])
        self.assertEqual(recovery['bundleDigest'], cold['bundleDigest'])
        return report

    def test_selected_inner_framework(self):
        report = self.acceptance('inner', 1, 'multi')
        node = next(iter(report['cases']['cold']['nodes'].values()))
        self.assertEqual(node['globalProperties'], {'configuration': 'Release', 'targetframework': 'net10.0'})
        self.assertEqual(node['targetFramework'], 'net10.0')

    def test_same_path_configurations_and_edge_convergence(self):
        report = self.acceptance('configured', 6, 'red:common|blue:common')
        cold = report['cases']['cold']
        shared = [n for n in cold['nodes'].values() if n['project'] == 'workspace/Shared/Shared.csproj']
        self.assertEqual({n['globalProperties']['flavor'] for n in shared}, {'red', 'blue'})
        self.assertEqual(len({n['id'] for n in shared}), 2)
        common = [n for n in cold['nodes'].values() if n['project'] == 'workspace/Common/Common.csproj']
        self.assertEqual(len(common), 1)
        self.assertNotIn('flavor', common[0]['globalProperties'])
        changed = report['cases']['edgeConverged']
        self.assertEqual(changed['output'], 'red:common|red:common')
        self.assertEqual(len(changed['nodes']), 5)
        self.assertEqual({a['project'] for a in changed['actions'] if not a['cacheHit']},
                         {'workspace/Right/Right.csproj', 'workspace/App/App.csproj'})
        self.assertEqual(changed['analyzedDependencies'],
                         {n['id']: sorted(n['dependencies']) for n in changed['nodes'].values()})
        for name in ('Left', 'Right'):
            node = next(n for n in changed['nodes'].values() if n['project'] == f'workspace/{name}/{name}.csproj')
            dependency = changed['nodes'][node['dependencies'][0]]
            self.assertEqual(dependency['globalProperties']['flavor'], 'red')


if __name__ == '__main__':
    unittest.main()
