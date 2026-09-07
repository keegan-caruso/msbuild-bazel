"""Black-box acceptance for roadmap milestone 1; no fixture compilation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[2]
EXPORTER = REPO / "tools/GraphExport/GraphExport.csproj"
DLL = REPO / "tools/GraphExport/bin/Release/net10.0/GraphExport.dll"


def write_fixture(work):
    files = {
        "global.json": '{"sdk":{"version":"10.0.100","rollForward":"disable"},"msbuild-sdks":{"Microsoft.Build.Traversal":"4.1.82"}}\n',
        "NuGet.Config": '<configuration><packageSources><clear/><add key="nuget" value="https://api.nuget.org/v3/index.json"/></packageSources></configuration>\n',
        "Directory.Build.props": '<Project><PropertyGroup><TargetFramework>net10.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings><UseAppHost>false</UseAppHost><Deterministic>true</Deterministic></PropertyGroup></Project>\n',
        "Directory.Build.targets": '<Project><Target Name="RejectExportCompilation" BeforeTargets="CoreCompile" Condition="\'$(BazelGraphExport)\' == \'true\'"><Error Text="Export must never compile fixture projects"/></Target></Project>\n',
        "build.proj": '<Project Sdk="Microsoft.Build.Traversal"><ItemGroup><ProjectReference Include="src/App/App.csproj"/></ItemGroup></Project>\n',
        "src/Shared/Shared.csproj": '<Project Sdk="Microsoft.NET.Sdk"/>\n',
        "src/Shared/Message.cs": 'namespace Shared; public static class Message { public static string Value => "shared-v1"; }\n',
        "src/Left/Left.csproj": '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><ProjectReference Include="../Shared/Shared.csproj"/></ItemGroup></Project>\n',
        "src/Left/Value.cs": 'namespace Left; public static class Value { public static string Text => Shared.Message.Value + ":left"; }\n',
        "src/Right/Right.csproj": '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><ProjectReference Include="../Shared/Shared.csproj"/></ItemGroup></Project>\n',
        "src/Right/Value.cs": 'namespace Right; public static class Value { public static string Text => Shared.Message.Value + ":right"; }\n',
        "src/App/App.csproj": '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType></PropertyGroup><ItemGroup><ProjectReference Include="../Left/Left.csproj"/><ProjectReference Include="../Right/Right.csproj"/></ItemGroup></Project>\n',
        "src/App/Program.cs": 'Console.WriteLine(Left.Value.Text + "|" + Right.Value.Text);\n',
    }
    for name, contents in files.items():
        path = work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)


class GraphExportAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # This assertion is intentionally red before the exporter is implemented.
        if not EXPORTER.is_file():
            raise AssertionError("Milestone 1 exporter is not implemented: " + str(EXPORTER))
        cls.dotnet_root = Path(os.environ.get("SPIKE_DOTNET_ROOT", REPO / ".tools/dotnet")).resolve()
        result = subprocess.run(["bash", str(REPO / "scripts/dotnet.sh"), "build", str(EXPORTER), "-c", "Release", "--nologo"], cwd=REPO, text=True, capture_output=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="msbuild-graph-"))
        self.work = self.root / "workspace"
        write_fixture(self.work)
        self.serial = 0

    def tearDown(self):
        if self._outcome.result.wasSuccessful():
            shutil.rmtree(self.root)

    def restore(self, work=None):
        work = work or self.work
        package_root = work / ".nuget/packages"
        package_root.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, NUGET_PACKAGES=str(package_root))
        result = subprocess.run(["bash", str(REPO / "scripts/dotnet.sh"), "msbuild", str(work / "build.proj"), "/t:Restore", "/p:Configuration=Release", f"/p:RestorePackagesPath={package_root}", "/nologo"], cwd=work, env=env, text=True, capture_output=True)
        (work / "restore.log").write_text(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def export(self, work=None, entries=None, error=None):
        self.serial += 1
        work = work or self.work
        output = self.root / f"graph-{self.serial}.json"
        request = self.root / f"request-{self.serial}.json"
        request.write_text(json.dumps({"schemaVersion": 1, "workspace": str(work), "dotnetRoot": str(self.dotnet_root), "sdkVersion": "10.0.100", "packageRoot": str(work / ".nuget/packages"), "entryPoints": entries or [{"project": "build.proj", "globalProperties": {"Configuration": "Release"}}], "output": str(output)}))
        result = subprocess.run([str(self.dotnet_root / "dotnet"), str(DLL), "--request", str(request)], cwd=REPO, text=True, capture_output=True)
        (self.root / f"export-{self.serial}.log").write_text(result.stdout + result.stderr)
        if error:
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(error, result.stderr)
            self.assertFalse(output.exists(), "failed export published a manifest")
            return None
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])
        return json.loads(output.read_text())

    def test_selected_existing_inner_framework_retains_declaration(self):
        project = self.work / "src/Shared/Shared.csproj"
        project.write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFrameworks>net10.0;netstandard2.1</TargetFrameworks></PropertyGroup></Project>')
        self.restore()
        graph = self.export(entries=[{"project": "src/Shared/Shared.csproj", "globalProperties": {"Configuration": "Release", "TargetFramework": "net10.0"}}])
        self.assertEqual(len(graph["nodes"]), 1)
        self.assertEqual(graph["nodes"][0]["globalProperties"], {"configuration": "Release", "targetframework": "net10.0"})
        self.assertIn("netstandard2.1", project.read_text())
        project.write_text(project.read_text().replace("net10.0;netstandard2.1", "netstandard2.1"))
        self.export(entries=[{"project": "src/Shared/Shared.csproj", "globalProperties": {"Configuration": "Release", "TargetFramework": "net10.0"}}], error="unsupported-configuration")

    def test_diamond_direct_edges_and_declared_boundaries(self):
        self.restore()
        graph = self.export()
        self.assertEqual(graph["schemaVersion"], 1)
        nodes = {Path(n["project"]).stem: n for n in graph["nodes"]}
        self.assertEqual(set(nodes), {"App", "Left", "Right", "Shared"})
        self.assertEqual(nodes["Shared"]["dependencies"], [])
        for name in ("Left", "Right"):
            self.assertEqual(nodes[name]["dependencies"], [nodes["Shared"]["id"]])
        self.assertEqual(set(nodes["App"]["dependencies"]), {nodes["Left"]["id"], nodes["Right"]["id"]})
        self.assertEqual(graph["entryPoints"], [nodes["App"]["id"]])
        for node in nodes.values():
            self.assertTrue({"project", "source", "import", "restore"}.issubset({i["kind"] for i in node["inputs"]}))
            self.assertTrue(any(o["path"].endswith(".dll") for o in node["outputs"]))
            self.assertTrue(all(len(i["sha256"]) == 64 for i in node["inputs"]))
        self.assertTrue(any(i["path"].endswith("build.proj") for i in graph["graphInputs"]))
        self.assertFalse(list(self.work.glob("src/*/bin")), "export compiled a subject project")

    def test_global_properties_distinguish_nodes(self):
        self.restore()
        entries = [{"project": "src/Shared/Shared.csproj", "globalProperties": {"Configuration": c}} for c in ("Release", "Debug")]
        graph = self.export(entries=entries)
        self.assertEqual(len(graph["nodes"]), 2)
        self.assertEqual(len({n["id"] for n in graph["nodes"]}), 2)
        self.assertEqual({n["globalProperties"]["configuration"] for n in graph["nodes"]}, {"Release", "Debug"})

    def test_restored_relocation_is_byte_equivalent(self):
        self.restore()
        first = self.export()
        moved = self.root / "a different checkout"
        write_fixture(moved)
        self.restore(moved)
        second = self.export(work=moved)
        self.assertEqual(first, second)
        self.assertNotIn(str(self.root), json.dumps(first))

    def test_source_change_changes_input_not_configured_identity(self):
        self.restore()
        before = self.export()
        with (self.work / "src/Shared/Message.cs").open("a") as stream:
            stream.write("// changed input\n")
        after = self.export()
        self.assertEqual([n["id"] for n in before["nodes"]], [n["id"] for n in after["nodes"]])
        self.assertNotEqual(before, after)

    def test_missing_explicit_source_is_rejected(self):
        self.restore()
        project = self.work / "src/Shared/Shared.csproj"
        project.write_text('<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><Compile Include="Missing.cs"/></ItemGroup></Project>')
        self.export(error="missing-input")

    def test_missing_restore_is_rejected(self):
        self.restore()
        (self.work / "src/Shared/obj/project.assets.json").unlink()
        self.export(error="missing-input")

    def test_source_path_escape_is_rejected(self):
        self.restore()
        outside = self.root / "outside.cs"
        outside.write_text("class Outside {}")
        (self.work / "src/Shared/Shared.csproj").write_text(f'<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><Compile Include="{outside}"/></ItemGroup></Project>')
        self.export(error="path-escape")

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlink_escape_is_rejected(self):
        self.restore()
        outside = self.root / "outside.cs"
        outside.write_text("class Outside {}")
        (self.work / "src/Shared/Escape.cs").symlink_to(outside)
        self.export(error="path-escape")

    def test_multi_targeting_is_rejected(self):
        self.restore()
        self.export(entries=[{"project": "src/Shared/Shared.csproj", "globalProperties": {"Configuration": "Release", "TargetFrameworks": "net10.0;net9.0"}}], error="unsupported-configuration")

    def test_rid_is_rejected(self):
        self.restore()
        self.export(entries=[{"project": "src/Shared/Shared.csproj", "globalProperties": {"Configuration": "Release", "RuntimeIdentifier": "linux-x64"}}], error="unsupported-configuration")

    def test_output_path_escape_is_rejected(self):
        self.restore()
        self.export(entries=[{"project": "src/Shared/Shared.csproj", "globalProperties": {"Configuration": "Release", "OutputPath": str(self.root / "outside-bin") + "/"}}], error="path-escape")

    def test_explicit_custom_input_is_declared(self):
        self.restore()
        (self.work / "src/Shared/input.txt").write_text("generator input\n")
        (self.work / "src/Shared/Shared.csproj").write_text('<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><BazelExtraInput Include="input.txt"/></ItemGroup></Project>')
        graph = self.export()
        node = next(n for n in graph["nodes"] if n["project"].endswith("Shared.csproj"))
        self.assertTrue(any(i["kind"] == "extra" and i["path"].endswith("input.txt") for i in node["inputs"]))


if __name__ == "__main__":
    unittest.main()
