"""Black-box checks for repository-owned C# code-style enforcement."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
DOTNET_ROOT = Path(os.environ.get("RULES_MSBUILD_DOTNET_ROOT", ROOT / ".tools/dotnet")).resolve()
DOTNET = DOTNET_ROOT / "dotnet"

PROJECT = """<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework>
    <ImplicitUsings>disable</ImplicitUsings>
    <Nullable>enable</Nullable>
  </PropertyGroup>
</Project>
"""

CLEAN_SOURCE = """using System;

namespace Probe;

public sealed class Sample
{
    private readonly int value = 1;

    public int Read()
    {
        return value + Environment.ProcessorCount;
    }
}
"""

STYLE_CASES = {
    "IDE0011": """namespace Probe;

public sealed class Sample
{
    public int Read(bool enabled)
    {
        if (enabled)
            return 1;
        return 0;
    }
}
""",
    "IDE0036": """namespace Probe;

sealed public class Sample
{
}
""",
    "IDE0051": """namespace Probe;

public sealed class Sample
{
    private int Unused()
    {
        return 1;
    }
}
""",
    "IDE0059": """namespace Probe;

public sealed class Sample
{
    public int Read()
    {
        int value = 1;
        value = 2;
        return value;
    }
}
""",
    "IDE0040": """namespace Probe;

class Sample
{
    int Read()
    {
        return 1;
    }
}
""",
    "IDE0044": """namespace Probe;

public sealed class Sample
{
    private int value = 1;

    public int Read()
    {
        return value;
    }
}
""",
    "IDE0055": """namespace Probe;

public sealed class Sample
{
public int Read( ){return 1;}
}
""",
    "IDE0065": """namespace Probe
{
    using System;

    public sealed class Sample
    {
        public string Read()
        {
            return Environment.NewLine;
        }
    }
}
""",
    "IDE0161": """using System;

namespace Probe
{
    public sealed class Sample
    {
        public string Read()
        {
            return Environment.NewLine;
        }
    }
}
""",
}

WARNING_SOURCE = """#warning owned warning

namespace Probe;

public sealed class Sample
{
}
"""

MISORDERED_SYSTEM_USINGS = """using System.Text;
using System;

namespace Probe;

public sealed class Sample
{
    public string Read()
    {
        return Environment.NewLine + typeof(StringBuilder).Name;
    }
}
"""


class CodeStyleEnforcementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not DOTNET.is_file():
            raise AssertionError(f"pinned dotnet not found: {DOTNET}")

        cls.evidence = Path(
            tempfile.mkdtemp(prefix="rules-msbuild-code-style-")
        ).resolve()
        shutil.copy2(ROOT / ".editorconfig", cls.evidence / ".editorconfig")
        shutil.copy2(ROOT / "global.json", cls.evidence / "global.json")

        tools = cls.evidence / "tools"
        tools.mkdir()
        shutil.copy2(ROOT / "tools/Directory.Build.props", tools / "Directory.Build.props")

        cls.projects = {
            "tool": cls._create_project(tools / "Probe"),
            "fixture": cls._create_project(cls.evidence / "tests/fixtures/Probe"),
        }
        cls.environment = os.environ.copy()
        cls.environment.update(
            DOTNET_ROOT=str(DOTNET_ROOT),
            DOTNET_CLI_HOME=str(cls.evidence / ".dotnet-home"),
            NUGET_PACKAGES=str(cls.evidence / ".nuget/packages"),
            DOTNET_NOLOGO="1",
            DOTNET_CLI_TELEMETRY_OPTOUT="1",
        )
        for name, project in cls.projects.items():
            result = cls._run(
                name=f"restore-{name}",
                command=[str(DOTNET), "restore", str(project)],
            )
            if result.returncode:
                raise AssertionError(result.stdout)

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "evidence"):
            print(f"Code-style evidence: {cls.evidence}")

    @classmethod
    def _create_project(cls, directory):
        directory.mkdir(parents=True, exist_ok=True)
        project = directory / "Probe.csproj"
        project.write_text(PROJECT)
        (directory / "Sample.cs").write_text(CLEAN_SOURCE)
        return project

    @classmethod
    def _run(cls, name, command, project=None):
        if project is not None:
            (project.parent / "Sample.cs").write_text(command)
            command = [
                str(DOTNET),
                "build",
                str(project),
                "--no-restore",
                "--no-incremental",
                "--nologo",
            ]
        result = subprocess.run(
            command,
            cwd=cls.evidence,
            env=cls.environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=120,
        )
        (cls.evidence / f"{name}.log").write_text(result.stdout)
        return result

    def assert_build_succeeds(self, scope, source, name):
        result = self._run(name, source, self.projects[scope])
        self.assertEqual(result.returncode, 0, result.stdout)
        return result

    def assert_build_fails_with(self, scope, source, diagnostic, name):
        result = self._run(name, source, self.projects[scope])
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(f"error {diagnostic}", result.stdout)
        return result

    def test_clean_owned_sources_compile(self):
        self.assert_build_succeeds("tool", CLEAN_SOURCE, "clean-tool")

    def test_selected_style_diagnostics_fail_as_errors(self):
        for diagnostic, source in STYLE_CASES.items():
            with self.subTest(diagnostic=diagnostic):
                self.assert_build_fails_with(
                    "tool", source, diagnostic, f"style-tool-{diagnostic}"
                )

    def test_compiler_warning_fails_in_owned_scopes(self):
        self.assert_build_fails_with("tool", WARNING_SOURCE, "CS1030", "warning-tool")

    def test_fixture_does_not_inherit_owned_build_policy(self):
        project = self.projects["fixture"]
        query = self._run(
            name="fixture-properties",
            command=[
                str(DOTNET),
                "msbuild",
                str(project),
                "-nologo",
                "-getProperty:EnforceCodeStyleInBuild",
                "-getProperty:TreatWarningsAsErrors",
            ],
        )
        self.assertEqual(query.returncode, 0, query.stdout)
        properties = json.loads(query.stdout)["Properties"]
        self.assertNotEqual(properties["EnforceCodeStyleInBuild"].lower(), "true")
        self.assertNotEqual(properties["TreatWarningsAsErrors"].lower(), "true")

        result = self.assert_build_succeeds(
            "fixture",
            WARNING_SOURCE,
            "fixture-warning",
        )
        self.assertIn("warning CS1030", result.stdout)

    def test_system_using_order_enforcement(self):
        project = self.projects["tool"]
        build = self._run("using-order-build", MISORDERED_SYSTEM_USINGS, project)
        if build.returncode:
            self.assertIn("error IDE0055", build.stdout)

        verify = self._run(
            name="using-order-format",
            command=[
                str(DOTNET),
                "format",
                str(project),
                "--verify-no-changes",
                "--no-restore",
                "--diagnostics",
                "IDE0040",
                "IDE0044",
                "IDE0055",
                "IDE0065",
                "IDE0161",
                "--severity",
                "warn",
            ],
        )
        self.assertNotEqual(verify.returncode, 0, verify.stdout)
        self.assertIn("error IMPORTS: Fix imports ordering.", verify.stdout)
        print(
            "System-using order: "
            + ("dotnet build enforced IDE0055; " if build.returncode else "dotnet build did not enforce IDE0055; ")
            + "dotnet format --verify-no-changes enforced IMPORTS"
        )


if __name__ == "__main__":
    unittest.main()
