"""C13 consumption boundary: real runner execution, never a warm consumer cache hit."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_graph import DOTNET_ROOT
from probe_graph_execution import probe


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GraphHandoffAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = Path(tempfile.mkdtemp(prefix='graph-handoff-')).resolve()
        cls.report = probe(cls.evidence / 'baseline')
        cls.generated = cls.evidence / 'baseline/workspace'
        cls.app = next(i for i, p in cls.report['nodes'].items() if p == 'src/App/App.csproj')
        cls.request = json.loads((cls.generated / f'bazel-bin/node_{cls.app}.request.json').read_text())
        for field in ('restore', 'graph_dependencies'):
            cls.request[field] = [str((cls.generated / p).resolve()) for p in cls.request[field]]
        for field in ('plugin', 'build_props', 'build_targets'):
            cls.request[field] = str((cls.generated / cls.request[field]).resolve())
        for item in cls.request['sources']:
            item['source'] = str((cls.generated / item['source']).resolve())
        print('Handoff evidence: ' + str(cls.evidence), flush=True)

    def run_consumer(self, name, mutation=None):
        root = self.evidence / name
        root.mkdir()
        request = json.loads(json.dumps(self.request))
        request.update(output=str(root / 'bundle'), diagnostics=str(root / 'diagnostics'))
        if mutation:
            dependency = root / 'dependency'
            shutil.copytree(request['graph_dependencies'][0], dependency)
            for item in [dependency, *dependency.rglob('*')]:
                item.chmod(0o755 if item.is_dir() else 0o644)
            request['graph_dependencies'][0] = str(dependency)
            mutation(dependency)
        path = root / 'request.json'
        path.write_text(json.dumps(request))
        result = subprocess.run([str(DOTNET_ROOT / 'dotnet'), str(self.generated / 'runner/ActionRunner.dll'), '--request', str(path)], cwd=self.generated, capture_output=True, text=True, timeout=180)
        log = result.stdout + result.stderr
        (root / 'run.log').write_text(log)
        (root / 'report.json').write_text(json.dumps(dict(schemaVersion=1,
            boundary='direct-action-runner', cacheEnabled=False,
            requestSha256=digest(path), returncode=result.returncode,
            replayRequested='SPIKE_REPLAY_REQUEST:' in log,
            compilationObserved='SPIKE_COMPILE:' in log,
            dependencies=[dict(resultsSha256=digest(Path(p) / 'results.json'),
                artifactsSha256=digest(Path(p) / 'artifacts.json')) for p in request['graph_dependencies']]), indent=2))
        return result, log, root

    def rejected(self, name, mutation, diagnostic, replay):
        result, log, root = self.run_consumer(name, mutation)
        self.assertNotEqual(result.returncode, 0, log)
        self.assertIn(diagnostic, log)
        self.assertNotIn('SPIKE_COMPILE:', log)
        self.assertEqual('SPIKE_REPLAY_REQUEST:' in log, replay)
        self.assertFalse((root / 'bundle/bundle.json').exists())

    @staticmethod
    def artifact(bundle):
        item = json.loads((bundle / 'artifacts.json').read_text())[0]
        return bundle / 'artifacts' / item['path']

    @staticmethod
    def semantic(mutation):
        def apply(bundle):
            path = bundle / 'results.json'
            payload = json.loads(path.read_text())
            mutation(payload)
            path.write_text(json.dumps(payload))
            seal = json.loads((bundle / 'bundle.json').read_text())
            seal['resultsSha256'] = digest(path)
            (bundle / 'bundle.json').write_text(json.dumps(seal))
        return apply

    def test_materialized_bundle_integrity(self):
        self.rejected('missing-artifact', lambda p: self.artifact(p).unlink(), 'dependency artifact missing or corrupt', False)
        self.rejected('corrupt-artifact', lambda p: self.artifact(p).write_bytes(b'corrupt'), 'dependency artifact missing or corrupt', False)
        self.rejected('interrupted-bundle', lambda p: (p / 'bundle.json').unlink(), 'dependency bundle incomplete', False)
        self.rejected('corrupt-results', lambda p: (p / 'results.json').write_text('{}'), 'dependency bundle metadata corrupt', False)

    def test_forced_replay_semantic_rejections(self):
        self.rejected('missing-target', self.semantic(lambda p: p['targets'].pop('GetTargetFrameworks')), 'dependency target missing', True)
        self.rejected('wrong-properties', self.semantic(lambda p: p['properties'].update(Configuration='Debug')), 'dependency global properties mismatch', True)
        def invalid_metadata(payload):
            item = next(items[0] for items in payload['targets'].values() if items)
            item['metadata']['InvalidPath'] = '${UNKNOWN}/invalid.dll'
        self.rejected('invalid-metadata', self.semantic(invalid_metadata), 'dependency unknown root token', True)

    def test_completed_output_cannot_be_reused_by_a_new_attempt(self):
        result, log, root = self.run_consumer('existing-output')
        self.assertEqual(result.returncode, 0, log)
        before = digest(root / 'bundle/bundle.json')
        result = subprocess.run([str(DOTNET_ROOT / 'dotnet'), str(self.generated / 'runner/ActionRunner.dll'), '--request', str(root / 'request.json')], cwd=self.generated, capture_output=True, text=True, timeout=180)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('graph output already contains a prior attempt', result.stderr)
        self.assertEqual(digest(root / 'bundle/bundle.json'), before)

    def test_simultaneous_consumers_replay_without_dependency_compilation(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            cases = list(pool.map(self.run_consumer, ('concurrent-a', 'concurrent-b')))
        roots = []
        for result, log, root in cases:
            self.assertEqual(result.returncode, 0, log)
            self.assertTrue((root / 'bundle/bundle.json').is_file())
            action = json.loads((root / 'diagnostics/action.json').read_text())
            self.assertEqual(action['compiledProjects'], ['App'])
            self.assertEqual(set(action['replayHits']), {'Left', 'Right', 'Shared'})
            roots.append(action['workspace'])
            app = root / 'bundle/artifacts/src/App/bin/Release/net10.0/App.dll'
            result = subprocess.run([str(DOTNET_ROOT / 'dotnet'), str(app)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), self.report['baselineOutput'])
        self.assertNotEqual(*roots)
        self.assertEqual(digest(cases[0][2] / 'bundle/results.json'), digest(cases[1][2] / 'bundle/results.json'))

if __name__ == '__main__':
    unittest.main()
