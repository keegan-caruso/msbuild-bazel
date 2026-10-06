"""The public sync executable has one graph backend and a fail-closed schema."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ["RULES_MSBUILD_DOTNET_ROOT"])
RUNNER = ROOT / "tools/ProjectSync/bin/Release/net10.0/ProjectSync.dll"


class GraphSyncTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="graph-sync-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup></Project>'
        (self.root / "App.csproj").write_text(self.project)
        (self.root / "Program.cs").write_text('System.Console.WriteLine(1);')

    def sync(self, mappings=None, flags=(), success=True):
        args = [str(SDK / "dotnet"), str(RUNNER), str(self.root), str(SDK / "sdk/10.0.400"), "App.csproj"]
        if mappings is not None:
            (self.root / "mappings.json").write_text(mappings if isinstance(mappings, str) else json.dumps(mappings))
            args += ["--mappings", "mappings.json"]
        result = subprocess.run(args + list(flags), capture_output=True, text=True, env=dict(os.environ, DOTNET_ROOT=str(SDK)))
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result.stdout + result.stderr

    def test_graph_is_the_only_default(self):
        self.sync()
        self.assertTrue((self.root / "graph.generated.json").is_file())
        self.assertFalse((self.root / "projects.generated.bzl").exists())
        self.sync(flags=["--check"])

    def test_removed_mode_flag_is_rejected(self):
        self.assertIn("Unknown", self.sync(flags=["--graph"], success=False))

    def test_configuration_is_direct(self):
        self.sync(flags=["--configuration", "Debug"])
        self.assertEqual(json.loads((self.root / "graph.generated.json").read_text())["Properties"]["Configuration"], "Debug")

    def test_stale_inputs_require_resync(self):
        self.sync()
        (self.root / "App.csproj").write_text(self.project.replace("net10.0", "net9.0"))
        self.assertIn("stale", self.sync(flags=["--check"], success=False).lower())

    def test_removed_backend_mappings_fail(self):
        for field in ["packages", "tests"]:
            with self.subTest(field=field):
                self.assertIn("do not support", self.sync({field: {}}, success=False))
        for field, value in [("tools", []), ("linuxWorker", True), ("outputMode", "reference"), ("referencePack", ":pack")]:
            with self.subTest(field=field):
                self.assertIn("explicit contract", self.sync({"projects": {"App.csproj": {field: value}}}, success=False))

    def test_duplicate_and_ambiguous_keys_fail(self):
        for text in ['{"projects":{},"projects":{}}', '{"projectDefaults":{"properties":{"Flavor":"a","flavor":"b"}}}']:
            self.assertIn("mapping", self.sync(text, success=False).lower())

    def test_invalid_paths_and_restore_contracts_fail(self):
        for mappings in [{"projects": {"../App.csproj": {}}}, {"projects": {"App.csproj": {"restoreInputs": ["props.xml"]}}}]:
            self.sync(mappings, success=False)

    def test_evaluation_reuse_requires_prepared_declared_compile_inputs(self):
        self.assertIn("preparedRestore", self.sync({"projectDefaults": {"evaluationReuseInputs": ["Program.cs"]}}, success=False))
        defaults = {"preparedRestore": True, "evaluationReuseInputs": ["@(Compile)"]}
        self.sync({"projectDefaults": defaults})
        contract = json.loads((self.root / "graph.generated.json").read_text())
        self.assertEqual(contract["Version"], 9)
        self.assertEqual(contract["EvaluationReuseInputs"], ["Program.cs"])
        defaults["evaluationReuseInputs"] = ["App.csproj"]
        self.assertIn("Compile", self.sync({"projectDefaults": defaults}, success=False))

    def test_owned_paths_cannot_be_overridden(self):
        for name in ["NetCoreSdkRoot", "PathMap", "RestoreSources"]:
            self.assertIn("declared inputs", self.sync({"projectDefaults": {"properties": {name: "/host"}}}, success=False))

    def test_document_contract_is_digest_bound(self):
        project = self.project.replace('</Project>', '<Target Name="Reviewed" /></Project>')
        (self.root / "App.csproj").write_text(project)
        mappings = {"projectDefaults": {"documents": {"App.csproj": {"sha256": hashlib.sha256(project.encode()).hexdigest(), "targets": ["Reviewed"], "tasks": [], "inputs": []}}}}
        self.sync(mappings)
        mappings["projectDefaults"]["documents"]["App.csproj"]["sha256"] = "0" * 64
        self.sync(mappings, success=False)

    def test_explicit_dependency_copies_preserve_ownership_and_require_review(self):
        library = self.root / 'Library'
        library.mkdir()
        (library / 'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
        (library / 'Code.cs').write_text('public class Library {}')
        (self.root / 'App.csproj').write_text(self.project.replace('</Project>', '<ItemGroup><ProjectReference Include="Library/Library.csproj" /></ItemGroup></Project>'))
        destination = 'bin/$(Configuration)/net10.0/Library.dll'
        source = 'Library/bin/$(Configuration)/net10.0/Library.dll'
        binding = {'referenceBoundary': True, 'dependencyCopies': {destination: source}}
        mapping = {'projects': {'App.csproj': binding}}
        self.sync(mapping)
        contract = (self.root / 'graph.generated.json').read_text()
        variants = json.loads(contract)['Projects']['App.csproj']['Configurations']
        self.assertEqual(variants[0]['DependencyCopies']['bin/Release/net10.0/Library.dll'], 'Library/bin/Release/net10.0/Library.dll')
        for destination, source in [('../outside/Library.dll', source),
                                    ('bin/Release/net10.0/Library.dll', 'bin/Release/net10.0/App.dll'),
                                    ('bin/Release/net10.0/Library.dll', 'Library/bin/Release/net10.0/Library.pdb'),
                                    ('unowned/Library.dll', 'Library/bin/Release/net10.0/Library.dll')]:
            with self.subTest(destination=destination, source=source):
                binding['dependencyCopies'] = {destination: source}
                self.sync(mapping, success=False)
                self.assertEqual((self.root / 'graph.generated.json').read_text(), contract)
        binding['referenceBoundary'] = False
        self.assertIn('reviewed reference boundary', self.sync(mapping, success=False))

    def test_ambiguous_dependency_copies_require_explicit_selection(self):
        for name in ['First', 'Second']:
            directory = self.root / name
            directory.mkdir()
            (directory / (name + '.csproj')).write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><AssemblyName>Shared</AssemblyName></PropertyGroup></Project>')
            (directory / 'Code.cs').write_text('public class ' + name + ' {}')
        references = ''.join('<ProjectReference Include="' + name + '/' + name + '.csproj" />' for name in ['First', 'Second'])
        (self.root / 'App.csproj').write_text(self.project.replace('</Project>', '<ItemGroup>' + references + '</ItemGroup></Project>'))
        mapping = {'projects': {'App.csproj': {'referenceBoundary': True}}}
        self.assertIn('Ambiguous graph dependency copy', self.sync(mapping, success=False))
        mapping['projects']['App.csproj']['dependencyCopies'] = {
            'bin/$(Configuration)/net10.0/' + destination + 'Shared.' + extension: 'First/bin/$(Configuration)/net10.0/Shared.' + extension
            for destination in ['', 'publish/'] for extension in ['dll', 'pdb', 'xml']}
        self.sync(mapping)
        variant = json.loads((self.root / 'graph.generated.json').read_text())['Projects']['App.csproj']['Configurations'][0]
        self.assertEqual(set(variant['DependencyCopies'].values()), {'First/bin/Release/net10.0/Shared.' + extension for extension in ['dll', 'pdb', 'xml']})


if __name__ == "__main__":
    unittest.main()
