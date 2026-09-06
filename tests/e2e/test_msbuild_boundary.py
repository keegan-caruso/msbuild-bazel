"""Black-box acceptance tests; committed before tools/spike.py exists."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
DRIVER = ROOT / "tools/spike.py"
FIXTURE = ROOT / "tests/fixtures/two-projects"
DOTNET = Path(os.environ.get("SPIKE_DOTNET_ROOT", ROOT / ".tools/dotnet")) / "dotnet"


class MsbuildBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(tempfile.mkdtemp(prefix="msbuild-e2e-"))
        self.workspace = self.directory / "workspace"
        shutil.copytree(FIXTURE, self.workspace)
        self.sequence = 0
        self.call("restore")
        self.restore_obj = self.directory / "app-restore"
        shutil.copytree(self.workspace / "App/obj", self.restore_obj)

    def tearDown(self):
        # Keep artifacts on failure; successful cases do not accumulate gigabytes.
        result = self._outcome.result
        failed = any(test is self for test, _ in result.failures + result.errors)
        if failed:
            print(f"Retained e2e workspace: {self.directory}", file=sys.stderr)
        else:
            shutil.rmtree(self.directory)

    def call(self, operation, project=None, dependencies=(), expect_success=True):
        self.sequence += 1
        output = self.directory / f"action-{self.sequence}"
        request = {
            "schemaVersion": 1, "operation": operation,
            "workspace": str(self.workspace), "output": str(output),
            "configuration": "Release",
        }
        if project:
            request.update(project=project, dependencies=[str(p) for p in dependencies])
        request_file = self.directory / f"request-{self.sequence}.json"
        request_file.write_text(json.dumps(request))
        completed = subprocess.run(
            [sys.executable, str(DRIVER), "--request", str(request_file)],
            cwd=ROOT, text=True, capture_output=True, timeout=180,
        )
        diagnostic = completed.stdout + completed.stderr
        if (output / "build.log").exists():
            diagnostic += (output / "build.log").read_text()
        if expect_success:
            self.assertEqual(completed.returncode, 0, diagnostic)
            self.assertTrue((output / "result.json").exists())
        else:
            self.assertNotEqual(completed.returncode, 0, diagnostic)
        return output, diagnostic

    def clean_outputs(self):
        for project in ("Shared", "App"):
            for folder in ("bin", "obj"):
                shutil.rmtree(self.workspace / project / folder, ignore_errors=True)
        shutil.copytree(self.restore_obj, self.workspace / "App/obj")

    def run_app(self):
        completed = subprocess.run(
            [str(DOTNET), str(self.workspace / "App/bin/Release/net10.0/App.dll")],
            text=True, capture_output=True, timeout=30,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return completed.stdout.strip()

    def assert_app_only(self, output):
        log = (output / "build.log").read_text()
        self.assertIn("SPIKE_COMPILE:App", log)
        self.assertNotIn("SPIKE_COMPILE:Shared", log)

    def test_traversal_baseline(self):
        output, _ = self.call("baseline")
        log = (output / "build.log").read_text()
        self.assertIn("SPIKE_COMPILE:Shared", log)
        self.assertIn("SPIKE_COMPILE:App", log)
        self.assertEqual(self.run_app(), "shared-v1/app-v1")

    def test_isolated_dependency_handoff_after_clean(self):
        shared, _ = self.call("project", "Shared")
        self.assertIn("SPIKE_COMPILE:Shared", (shared / "build.log").read_text())
        self.clean_outputs()
        app, _ = self.call("project", "App", [shared])
        self.assert_app_only(app)
        self.assertEqual(self.run_app(), "shared-v1/app-v1")

    def test_app_edit_reuses_shared_bundle(self):
        shared, _ = self.call("project", "Shared")
        self.call("project", "App", [shared])
        self.clean_outputs()
        program = self.workspace / "App/Program.cs"
        program.write_text(program.read_text().replace("app-v1", "app-v2"))
        app, _ = self.call("project", "App", [shared])
        self.assert_app_only(app)
        self.assertEqual(self.run_app(), "shared-v1/app-v2")

    def test_missing_dependency_artifact_fails(self):
        shared, _ = self.call("project", "Shared")
        manifest = json.loads((shared / "result.json").read_text())
        self.assertTrue(manifest["artifacts"])
        (shared / "artifacts" / manifest["artifacts"][0]).unlink()
        self.clean_outputs()
        _, diagnostic = self.call("project", "App", [shared], expect_success=False)
        self.assertIn("dependency", diagnostic.lower())

    def test_configuration_mismatch_fails(self):
        shared, _ = self.call("project", "Shared")
        path = shared / "result.json"
        manifest = json.loads(path.read_text())
        manifest["configuration"] = "Debug"
        path.write_text(json.dumps(manifest))
        _, diagnostic = self.call("project", "App", [shared], expect_success=False)
        self.assertIn("configuration", diagnostic.lower())

    def test_relocation_is_explicitly_unsupported(self):
        shared, _ = self.call("project", "Shared")
        original = self.workspace
        self.workspace = self.directory / "relocated"
        shutil.copytree(original, self.workspace)
        shutil.rmtree(original)
        _, diagnostic = self.call("project", "App", [shared], expect_success=False)
        self.assertIn("workspace", diagnostic.lower())


if __name__ == "__main__":
    unittest.main()
