"""R06 characterization of existing MSBuild and Bazel output ownership."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = {f'src/{n}/{n}.csproj' for n in ('Shared', 'Left', 'Right', 'App')}


class LifecycleAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output = Path(tempfile.mkdtemp(prefix='msbuild-lifecycle-')) / 'probe'
        print('Lifecycle evidence: ' + str(cls.output), file=sys.stderr)
        result = subprocess.run([sys.executable, str(ROOT / 'tools/probe_lifecycle.py'), '--output', str(cls.output)],
            cwd=ROOT, text=True, capture_output=True, timeout=1800)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.report = json.loads((cls.output / 'report.json').read_text())

    def evidence(self, path):
        full = (self.output / path).resolve()
        self.assertTrue(full.is_relative_to(self.output.resolve()))
        self.assertTrue(full.is_file(), str(full))
        return full

    def case(self, name, executed):
        case = self.report['cases'][name]
        self.assertEqual(case['returncode'], 0)
        self.assertEqual(case['applicationOutput'], 'shared-v1:left|shared-v1:right')
        self.assertEqual(set(case['executedProjects']), executed)
        self.evidence(case['executionLog'])
        for action in case['actions']:
            self.assertIn(action['project'], PROJECTS)
            self.assertFalse(action['remotable'])
            self.assertFalse(action['remoteCacheable'])
            if not action['cacheHit']:
                self.assertIn(action['runner'], ('darwin-sandbox', 'linux-sandbox'))
                markers = [line.split('RULES_MSBUILD_COMPILE:', 1)[1].strip()
                    for line in self.evidence(action['log']).read_text().splitlines() if 'RULES_MSBUILD_COMPILE:' in line]
                self.assertEqual(markers, [action['project']])
                targets = next(arg[3:] for arg in action['command'] if arg.startswith('-t:')).split(';')
                self.assertIn('Build', targets)
                self.assertNotIn('Clean', targets)
                self.assertNotIn('Rebuild', targets)
        canonical = {}
        self.assertEqual(len({Path(p).parts[0] for p in case['bundleFiles']}), 4)
        for path, metadata in case['bundleFiles'].items():
            retained = self.evidence(metadata['file'])
            self.assertEqual(hashlib.sha256(retained.read_bytes()).hexdigest(), metadata['sha256'])
            self.assertEqual(bool(retained.stat().st_mode & 0o111), metadata['executable'])
            canonical[path] = {k: metadata[k] for k in ('sha256', 'executable')}
        self.assertEqual(hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(',', ':')).encode()).hexdigest(), case['bundleDigest'])
        self.assertEqual(case['bundleDigest'], self.report['cases']['cold']['bundleDigest'])
        return case

    def test_ordinary_clean_owns_recorded_release_outputs(self):
        self.assertEqual(self.report['baselineOutput'], 'shared-v1:left|shared-v1:right')
        clean = self.report['ordinary']['clean']
        self.assertEqual(clean['compiledProjects'], [])
        for key in ('releaseAssembliesAbsent', 'debugOutputsPreserved', 'restoreAssetsPreserved', 'userFilePreserved'):
            self.assertTrue(clean[key], key)
        self.evidence(clean['log'])

    def test_ordinary_rebuild_really_compiles_and_preserves_debug(self):
        for name in ('cold', 'afterClean', 'rebuild'):
            case = self.report['ordinary'][name]
            self.assertEqual(case['compiledProjects'], ['App', 'Left', 'Right', 'Shared'])
            self.assertEqual(case['returncode'], 0)
            self.evidence(case['log'])
        for name in ('afterClean', 'rebuild'):
            self.assertEqual(self.report['ordinary'][name]['applicationOutput'], self.report['baselineOutput'])
        self.assertTrue(self.report['ordinary']['rebuild']['debugOutputsPreserved'])
        self.assertTrue(self.report['ordinary']['rebuild']['userFilePreserved'])

    def test_isolated_rebuild_is_a_distinct_failed_control(self):
        failure = self.report['ordinary']['isolatedRebuild']
        self.assertNotEqual(failure['returncode'], 0)
        self.assertEqual(failure['diagnostic'], 'MSB4252')
        self.assertIn('MSB4252', self.evidence(failure['log']).read_text())
        self.assertIn('-graphBuild', failure['command'])
        self.assertIn('-isolateProjects', failure['command'])
        self.assertTrue(failure['appAssemblyAbsentAfterFailure'])
        self.assertNotIn('-graphBuild', self.report['ordinary']['rebuild']['command'])
        self.assertNotIn('-isolateProjects', self.report['ordinary']['rebuild']['command'])

    def test_bazel_clean_removes_whole_trees_and_reuses_disk_cache(self):
        self.case('cold', PROJECTS)
        clean = self.report['bazelClean']
        for key in ('declaredBundlesAbsent', 'injectedTreeFileRemoved', 'sourceInputsPreserved',
                'buildPlanPreserved', 'userFilePreserved', 'diskCachePreserved', 'otherOutputBasePreserved'):
            self.assertTrue(clean[key], key)
        self.evidence(clean['log'])
        self.assertEqual(set(self.case('afterClean', set())['cacheHitProjects']), PROJECTS)

    def test_bazel_expunge_removes_base_but_preserves_other_ownership(self):
        state = self.report['bazelExpunge']
        for key in ('outputBaseAbsent', 'diskCachePreserved', 'sourceInputsPreserved', 'userFilePreserved', 'otherOutputBasePreserved'):
            self.assertTrue(state[key], key)
        self.evidence(state['log'])
        self.assertEqual(set(self.case('afterExpunge', set())['cacheHitProjects']), PROJECTS)

    def test_deleted_producer_and_consumer_outputs_recover(self):
        for name in ('producerDeleted', 'consumerDeleted'):
            case = self.case(name, set())
            self.assertTrue(case['deletedBundleAbsentBeforeBuild'])
            self.assertIn(case['deletedProject'], case['cacheHitProjects'])

    def test_fresh_compilation_is_distinct_from_cache_recovery(self):
        case = self.case('forcedFreshBuild', PROJECTS)
        self.assertEqual(case['cacheHitProjects'], [])
        self.assertTrue(case['outputBaseAndCacheAbsentBeforeBuild'])
        self.assertTrue(self.report['preparationWorkspaceAbsent'])
        self.assertEqual(self.report['scope'], 'R06-lifecycle-characterization')
        self.assertIn('not implemented', self.report['graphLifecycleApi'])
