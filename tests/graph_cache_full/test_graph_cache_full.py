"""Full managed-package graph cache acceptance, including the R01 controls."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'graph_cache'))
import test_graph_cache as package_free


class GraphCacheAcceptance(package_free.GraphCacheAcceptance):
    probe_args = []
    expected_scope = 'R02-managed-package-cache'

    def test_branch_package_upgrade(self):
        cold = self.case('packageCold', package_free.PROJECTS,
            'shared-v1:left/package-v1|shared-v1:right', cache_hits=[])
        upgrade = self.case('packageUpgrade', ['Left', 'App'],
            'shared-v1:left/package-v2|shared-v1:right')
        for case in (cold, upgrade):
            self.assertTrue(case['preparationWorkspaceAbsent'])
            self.assertEqual(case['applicationOutput'], case['ordinaryOutput'])
        evidence = self.report['packageUpgrade']
        self.assertEqual((evidence['beforeVersion'], evidence['afterVersion']), ('1.0.0', '1.0.1'))
        self.assertNotEqual(evidence['beforePayloadSha256'], evidence['afterPayloadSha256'])
        self.assertNotEqual(evidence['beforeArchiveSha256'], evidence['afterArchiveSha256'])
        self.assertTrue(evidence['preparationWorkspaceAbsent'])
        pins = json.loads(self.evidence(evidence['pins']).read_text())
        for prefix in ('before', 'after'):
            version = evidence[prefix + 'Version']
            archive = self.evidence(f'pinned-package-archives/Spike.Binary.{version}.nupkg')
            self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), pins['Spike.Binary/' + version])
            self.assertEqual(evidence[prefix + 'ArchiveSha256'], pins['Spike.Binary/' + version])
            payload = self.evidence(evidence[prefix + 'PayloadFile'])
            self.assertEqual(hashlib.sha256(payload.read_bytes()).hexdigest(), evidence[prefix + 'PayloadSha256'])
            with zipfile.ZipFile(archive) as package:
                self.assertEqual(payload.read_bytes(), package.read('lib/net10.0/Spike.Binary.dll'))
            manifest = json.loads(self.evidence(evidence[prefix + 'Manifest']).read_text())
            nodes = {n['project'].removeprefix('workspace/'): n for n in manifest['nodes']}
            for project in ('Shared', 'Right'):
                self.assertFalse([i for i in nodes[package_free.PROJECTS[project]]['inputs'] if i['kind'] == 'package'])
            for project in ('Left', 'App'):
                self.assertTrue([i for i in nodes[package_free.PROJECTS[project]]['inputs'] if i['kind'] == 'package'])

    def test_package_disk_cache_recovery(self):
        case = self.case('packageDiskCache', [], 'shared-v1:left/package-v1|shared-v1:right', cache_hits=package_free.PROJECTS)
        self.assertTrue(case['outputsAbsentBeforeBuild'])
        self.assertTrue(case['outputBaseAbsentBeforeBuild'])
        self.assertTrue(case['preparationWorkspaceAbsent'])
        self.assertEqual(case['bundleDigest'], self.report['cases']['packageCold']['bundleDigest'])

    def test_package_relocated_recovery(self):
        case = self.case('packageRelocated', [], 'shared-v1:left/package-v1|shared-v1:right', cache_hits=package_free.PROJECTS)
        self.assertTrue(case['outputsAbsentBeforeBuild'])
        self.assertTrue(case['outputBaseAbsentBeforeBuild'])
        self.assertTrue(case['preparationWorkspaceAbsent'])
        self.assertTrue(case['producerWorkspaceAbsent'])
        self.assertNotEqual(case['producerWorkspace'], case['consumerWorkspace'])
        self.assertEqual(case['bundleDigest'], self.report['cases']['packageCold']['bundleDigest'])

    def test_missing_corrupt_and_stale_inputs(self):
        for name, diagnostic in (('missingSource', 'missing-input'), ('missingPackage', 'missing-input'),
                ('corruptPackage', 'hash-mismatch'), ('staleManifest', 'stale-manifest'), ('staleRestore', 'stale-restore')):
            with self.subTest(case=name):
                case = self.report['failures'][name]
                self.assertNotEqual(case['returncode'], 0)
                self.assertEqual(case['diagnostic'], diagnostic)
                self.assertEqual(case['executedProjects'], [])
                self.assertFalse(case['publishedPlan'])
                self.assertTrue(case['preservedManifest'])
                manifest = self.evidence(case['manifest'])
                self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(), case['manifestSha256'])
                log = self.evidence(case['log']).read_text()
                self.assertIn(diagnostic, log)
                self.assertNotIn('SPIKE_COMPILE:', log)

    def test_stale_metadata_cannot_replace_a_warm_published_plan(self):
        for name, diagnostic in (('stalePrivateAssets', 'stale-restore'),
                ('namespacedStaleRestore', 'stale-restore'),
                ('namespacedUnpinnedVersion', 'unsupported-package')):
            with self.subTest(case=name):
                case = self.report['failures'][name]
                self.assertNotEqual(case['returncode'], 0)
                self.assertNotEqual(case['exportReturncode'], 0)
                self.assertEqual(case['diagnostic'], diagnostic)
                self.assertEqual(case['exportDiagnostic'], diagnostic)
                self.assertFalse(case['publishedPlan'])
                self.assertFalse(case['freshManifestPublished'])
                self.assertTrue(case['existingPlanIntact'])
                self.assertTrue(case['preservedManifest'])
                self.assertEqual(case['executedProjects'], [])
                self.assertEqual(case['bazelInvocationsBefore'], case['bazelInvocationsAfter'])
                self.assertEqual(case['bazelInvocationsBefore'][-1], name + '-baseline')
                before = json.loads(self.evidence(case['beforePlan']).read_text())
                after = json.loads(self.evidence(case['afterPlan']).read_text())
                self.assertIn('BUILD.bazel', before)
                self.assertIn('graph.json', before)
                self.assertTrue(any(p.startswith('package-manifests/') for p in before))
                self.assertEqual(before, after)
                for logical, metadata in before.items():
                    path = self.evidence(case['retainedPlan'] + '/' + logical)
                    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), metadata['sha256'])
                    self.assertEqual(bool(path.stat().st_mode & 0o111), metadata['executable'])
                manifest = self.evidence(case['manifest'])
                self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(), case['manifestSha256'])
                mutation = self.evidence(case['mutatedProject']).read_text()
                if name == 'stalePrivateAssets':
                    self.assertIn('PrivateAssets="all"', mutation)
                else:
                    self.assertIn('xmlns="http://schemas.microsoft.com/developer/msbuild/2003"', mutation)
                    self.assertIn('Version="[1.0.1]"' if name == 'namespacedStaleRestore' else 'Version="1.0.0"', mutation)
                for field in ('log', 'exportLog'):
                    log = self.evidence(case[field]).read_text()
                    self.assertIn(diagnostic, log)
                    self.assertNotIn('SPIKE_COMPILE:', log)
