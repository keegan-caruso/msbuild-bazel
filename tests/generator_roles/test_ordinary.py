"""Ordinary MSBuild oracle for the R05 generator/reference-role fixture."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/generator-roles"
DOTNET_ROOT = Path(os.environ.get("RULES_MSBUILD_DOTNET_ROOT", ROOT / ".tools/dotnet"))
PROJECTS = (
    "Shared/Shared.csproj",
    "ClassicGenerator/ClassicGenerator.csproj",
    "IncrementalGenerator/IncrementalGenerator.csproj",
    "OrderOnly/OrderOnly.csproj",
    "App/App.csproj",
)


class OrdinaryGeneratorRoles(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="generator-roles-ordinary-")).resolve()
        print("Ordinary generator-role evidence: " + str(self.root), flush=True)
        self.workspace = self.root / "workspace"
        self.observations = self.root / "observations"
        shutil.copytree(FIXTURE, self.workspace)
        self.dotnet = DOTNET_ROOT / "dotnet"
        self.assertTrue(self.dotnet.is_file(), "install or select the pinned .NET SDK")
        self.environment = dict(
            os.environ,
            DOTNET_CLI_HOME=str(self.root / "dotnet-home"),
            DOTNET_CLI_TELEMETRY_OPTOUT="1",
            MSBUILDDISABLENODEREUSE="1",
            NUGET_PACKAGES=str(self.root / "packages"),
        )
        self.command_number = 0

    def run_command(self, name, arguments, expect_success=True):
        self.command_number += 1
        result = subprocess.run(
            [str(argument) for argument in arguments],
            cwd=self.workspace,
            env=self.environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=300,
        )
        (self.root / f"{self.command_number:02d}-{name}.log").write_text(result.stdout)
        if expect_success:
            self.assertEqual(result.returncode, 0, result.stdout)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result.stdout

    def restore(self):
        for project in PROJECTS:
            self.run_command(
                "restore-" + Path(project).stem,
                [
                    self.dotnet,
                    "restore",
                    project,
                    "--configfile",
                    "NuGet.Config",
                    "--nologo",
                ],
            )

    def build(self, name, expect_success=True):
        return self.run_command(
            name,
            [
                self.dotnet,
                "msbuild",
                "App/App.csproj",
                "-t:Build",
                "-p:Configuration=Release",
                f"-p:GeneratorRolesObservationDirectory={self.observations}",
                "-nodeReuse:false",
                "-nologo",
            ],
            expect_success,
        )

    def app_output(self):
        return self.run_command(
            "app",
            [self.dotnet, "App/bin/Release/net10.0/App.dll"],
        ).strip().splitlines()

    def observed_app_roles(self):
        lines = (self.observations / "App.roles.txt").read_text(encoding="utf-8-sig").splitlines()
        return {
            role: [path for line in lines if line.startswith(role + "|")
                   for path in [line.split("|", 1)[1]]]
            for role in ("Analyzer", "ReferencePath", "ReferenceCopyLocalPaths")
        }

    def test_baseline_reference_roles_and_targeted_mutations(self):
        self.assertFalse(list(FIXTURE.glob("**/bin")), "source fixture must remain uncompiled")
        self.assertFalse(list(FIXTURE.glob("**/obj")), "source fixture must remain unrestored")
        self.restore()

        baseline = self.build("baseline")
        self.assertIn("warning GEN001", baseline)
        self.assertIn("warning GEN002", baseline)
        self.assertEqual(
            self.app_output(),
            [
                "shared=shared-v1",
                "classic=fixture-v1|editor-v1|alpha=one,sentinel=warn",
                "incremental=fixture-v1|editor-v1|alpha=one,sentinel=warn",
            ],
        )

        roles = self.observed_app_roles()
        for generator in ("ClassicGenerator.dll", "IncrementalGenerator.dll"):
            self.assertTrue(any(path.endswith("/" + generator) for path in roles["Analyzer"]))
            self.assertFalse(any(path.endswith("/" + generator) for path in roles["ReferencePath"]))
            self.assertFalse(any(path.endswith("/" + generator)
                                 for path in roles["ReferenceCopyLocalPaths"]))
        self.assertTrue(any(path.endswith("/Shared.dll") for path in roles["ReferencePath"]))
        self.assertTrue(any(path.endswith("/Shared.dll")
                            for path in roles["ReferenceCopyLocalPaths"]))
        for role in roles.values():
            self.assertFalse(any(path.endswith("/OrderOnly.dll") for path in role))

        app_output = self.workspace / "App/bin/Release/net10.0"
        runtime_names = {path.name for path in app_output.iterdir() if path.is_file()}
        self.assertIn("Shared.dll", runtime_names)
        self.assertTrue({"ClassicGenerator.dll", "IncrementalGenerator.dll", "OrderOnly.dll"}.isdisjoint(runtime_names))
        self.assertEqual(
            (self.workspace / "OrderOnly/bin/Release/net10.0/order-only.state")
            .read_text(encoding="utf-8-sig").strip(),
            "order-only-v1",
        )
        for generator in ("ClassicGenerator", "IncrementalGenerator"):
            generator_output = self.workspace / generator / "bin/Release/net10.0"
            self.assertFalse(list(generator_output.glob("Microsoft.CodeAnalysis*.dll")))

        editorconfig = self.workspace / "App/.editorconfig"
        original_config = editorconfig.read_text()
        editorconfig.write_text(original_config.replace("severity = warning", "severity = error"))
        severity = self.build("severity-error", expect_success=False)
        self.assertIn("error GEN001", severity)
        self.assertIn("error GEN002", severity)

        editorconfig.write_text(original_config.replace("editor-v1", "editor-v2"))
        app_project = self.workspace / "App/App.csproj"
        app_project.write_text(app_project.read_text().replace("fixture-v1", "fixture-v2"))
        values = self.workspace / "App/values"
        (values / "alpha.txt").write_text("two\n")
        (values / "sentinel.txt").unlink()
        (values / "beta.txt").write_text("added\n")
        changed = self.build("changed-and-removed")
        self.assertNotIn("GEN001", changed)
        self.assertNotIn("GEN002", changed)
        self.assertEqual(
            self.app_output(),
            [
                "shared=shared-v1",
                "classic=fixture-v2|editor-v2|alpha=two,beta=added",
                "incremental=fixture-v2|editor-v2|alpha=two,beta=added",
            ],
        )


if __name__ == "__main__":
    unittest.main()
