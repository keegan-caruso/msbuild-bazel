"""R01 package-free cache acceptance. R02 package obligations remain in the contract.

Run separately from existing acceptance: python3 -m unittest discover -s tests/graph_cache -v
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
PROBE = REPO / "tools/probe_graph_cache.py"
PROJECTS = {name: f"src/{name}/{name}.csproj" for name in ("App", "Left", "Right", "Shared")}
ALL = set(PROJECTS.values())
BASELINE = "shared-v1:left|shared-v1:right"


class GraphCacheAcceptance(unittest.TestCase):
    probe_args = ["--package-free"]
    expected_scope = "R01-package-free-cache"
    @classmethod
    def setUpClass(cls):
        if not PROBE.is_file():
            raise AssertionError("Milestone 3 cache probe is not implemented: tools/probe_graph_cache.py")
        cls.output = Path(tempfile.mkdtemp(prefix="msbuild-graph-cache-")) / "probe"
        # Retain evidence even on success: Bazel caches may contain read-only trees.
        print(f"Graph cache evidence: {cls.output}", file=sys.stderr)
        result = subprocess.run([sys.executable, str(PROBE), "--output", str(cls.output), *cls.probe_args],
                                cwd=REPO, text=True, capture_output=True, timeout=1800)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        cls.report = json.loads((cls.output / "report.json").read_text())

    def evidence(self, name):
        path = (self.output / name).resolve()
        self.assertTrue(path.is_relative_to(self.output.resolve()), "evidence escapes output directory")
        self.assertTrue(path.is_file(), str(path))
        return path

    def case(self, name, executed, output=BASELINE, cache_hits=None):
        case = self.report["cases"][name]
        self.assertEqual(case["returncode"], 0, name)
        self.assertEqual(case["applicationReturncode"], 0, name)
        self.assertEqual(case["applicationOutput"], output, name)
        self.assertEqual(set(case["executedProjects"]), {PROJECTS[p] for p in executed}, name)
        self.assertEqual(len(case["executedProjects"]), len(executed), "duplicate configured action execution")
        if cache_hits is not None:
            self.assertEqual(set(case["cacheHitProjects"]), {PROJECTS[p] for p in cache_hits}, name)
        actions = case["executions"]
        self.assertEqual({a["project"] for a in actions if not a["cacheHit"]}, set(case["executedProjects"]))
        self.assertEqual({a["project"] for a in actions if a["cacheHit"]}, set(case["cacheHitProjects"]))
        self.assertEqual(len({a["nodeId"] for a in actions}), len(actions), "duplicate configured node")
        for action in actions:
            self.assertIn(action["project"], ALL)
            self.assertFalse(action["remotable"])
            self.assertFalse(action["remoteCacheable"])
            if not action["cacheHit"]:
                self.assertIn(action["runner"], ("darwin-sandbox", "linux-sandbox"))
                log = self.evidence(action["log"]).read_text()
                markers = [line.split("SPIKE_COMPILE:", 1)[1].strip()
                           for line in log.splitlines() if "SPIKE_COMPILE:" in line]
                self.assertEqual(markers, [action["project"]], "consumer compiled dependency or compiled twice")
        self.evidence(case["executionLog"])
        self.assertTrue(case["bundleFiles"], "no recovered artifacts")
        self.assertEqual(len({Path(p).parts[0] for p in case["bundleFiles"]}), 4, "missing configured bundle")
        canonical = {}
        for path, metadata in case["bundleFiles"].items():
            self.assertFalse(Path(path).is_absolute())
            self.assertNotIn("..", Path(path).parts)
            payload = self.evidence(metadata["file"])
            self.assertEqual(hashlib.sha256(payload.read_bytes()).hexdigest(), metadata["sha256"])
            self.assertEqual(bool(payload.stat().st_mode & 0o111), metadata["executable"])
            canonical[path] = {"sha256": metadata["sha256"], "executable": metadata["executable"]}
        digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(case["bundleDigest"], digest)
        return case

    def test_cold_and_unchanged(self):
        self.assertEqual(self.report["schemaVersion"], 1)
        self.assertEqual(self.report["scope"], self.expected_scope)
        self.assertEqual(self.report["baselineOutput"], BASELINE)
        self.case("cold", PROJECTS, cache_hits=[])
        self.case("unchanged", [])

    def test_app_source_edit(self):
        self.case("appEdit", ["App"], BASELINE + "|app-v2")

    def test_one_branch_source_edit(self):
        self.case("leftEdit", ["Left", "App"], "shared-v1:left-v2|shared-v1:right")

    def test_shared_source_edit(self):
        case = self.case("sharedEdit", PROJECTS, "shared-v2:left|shared-v2:right")
        self.assertEqual(case["applicationOutput"], case["ordinaryOutput"])

    def test_shared_import_edit(self):
        self.case("importEdit", PROJECTS, BASELINE + "|config-v2")

    def test_graph_edge_added_before_analysis(self):
        self.case("graphEdgeAdded", ["Right", "App"], "shared-v1:left|shared-v1:right+shared-v1:left")
        evidence = self.report["graphEdgeAdded"]
        before = json.loads(self.evidence(evidence["beforeManifest"]).read_text())
        after = json.loads(self.evidence(evidence["afterManifest"]).read_text())
        old = {n["project"].removeprefix("workspace/"): n for n in before["nodes"]}
        new = {n["project"].removeprefix("workspace/"): n for n in after["nodes"]}
        right, left, shared = (PROJECTS[p] for p in ("Right", "Left", "Shared"))
        self.assertEqual(set(new), ALL)
        self.assertEqual({p: n["id"] for p, n in old.items()}, {p: n["id"] for p, n in new.items()})
        self.assertEqual(set(old[right]["dependencies"]), {old[shared]["id"]})
        self.assertEqual(set(new[right]["dependencies"]), {new[shared]["id"], new[left]["id"]})
        self.assertEqual(evidence["analyzedDependencies"][new[right]["id"]], sorted(new[right]["dependencies"]))
        self.assertLess(evidence["planGenerationSequence"], evidence["analysisSequence"])
        self.evidence(evidence["analysisLog"])

    def test_clean_disk_cache_recovery(self):
        case = self.case("diskCache", [], cache_hits=PROJECTS)
        self.assertTrue(case["outputsAbsentBeforeBuild"])
        self.assertTrue(case["outputBaseAbsentBeforeBuild"])
        self.assertEqual(case["bundleDigest"], self.report["cases"]["cold"]["bundleDigest"])

    def test_relocated_cache_recovery_without_producer(self):
        case = self.case("relocated", [], cache_hits=PROJECTS)
        self.assertTrue(case["producerWorkspaceAbsent"])
        self.assertNotEqual(case["producerWorkspace"], case["consumerWorkspace"])
        self.assertTrue(case["outputsAbsentBeforeBuild"])
        self.assertTrue(case["outputBaseAbsentBeforeBuild"])
        self.assertEqual(case["bundleDigest"], self.report["cases"]["cold"]["bundleDigest"])



if __name__ == "__main__":
    unittest.main()
