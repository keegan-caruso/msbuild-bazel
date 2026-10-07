"""The public sync executable has one graph backend and a fail-closed schema."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
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

    def source_group(self):
        directory = self.root / "LongDirectoryPrefix" / "Sources"
        directory.mkdir(parents=True)
        for i in range(40):
            (directory / f"Source{i:02}.cs").write_text(f"public class Source{i:02} {{}}")
        return directory

    def test_globs_compact_prefixes_with_pinned_membership(self):
        directory = self.source_group()
        self.sync()
        generated = (self.root / "graph.generated.bzl").read_text()
        self.assertIn('"LongDirectoryPrefix/Sources/*.cs"', generated)
        self.assertIn('"Source00.cs"', generated)
        self.assertNotIn('"LongDirectoryPrefix/Sources/Source00.cs"', generated)
        contract = json.loads((self.root / "graph.generated.json").read_text())
        self.assertIn("LongDirectoryPrefix/Sources/Source00.cs", contract["Projects"]["App.csproj"]["Configurations"][0]["Inputs"])
        self.sync(flags=["--check"])
        (directory / "Source00.cs").rename(directory / "Renamed.cs")
        self.assertIn("stale", self.sync(flags=["--check"], success=False).lower())
        self.sync()

    def test_glob_fallbacks_preserve_package_rejection(self):
        self.sync()
        self.assertNotIn("sync_source_globs", (self.root / "graph.generated.bzl").read_text())
        directory = self.source_group()
        project = self.root / "App.csproj"
        project.write_text(self.project.replace('</Project>', '<ItemGroup><Compile Remove="LongDirectoryPrefix/Sources/Source00.cs" /></ItemGroup></Project>'))
        self.sync()
        self.assertNotIn("sync_source_globs", (self.root / "graph.generated.bzl").read_text())
        project.write_text(self.project)
        hidden = directory / ".Hidden.cs"
        hidden.write_text("public class Hidden {}")
        self.sync()
        self.assertNotIn("sync_source_globs", (self.root / "graph.generated.bzl").read_text())
        hidden.unlink()
        for boundary in ["BUILD", "BUILD.bazel"]:
            (directory.parent / boundary).write_text('exports_files([])')
            self.assertIn("root Bazel package", self.sync(success=False))
            (directory.parent / boundary).unlink()
        original = directory / "Source00.cs"
        original.rename(directory / "source.txt")
        original.symlink_to("source.txt")
        self.sync()
        self.assertNotIn("sync_source_globs", (self.root / "graph.generated.bzl").read_text())

    def test_globs_preserve_configuration_specific_input_sets(self):
        directory = self.source_group()
        (self.root / "App.csproj").write_text(self.project.replace('<TargetFramework>net10.0</TargetFramework>',
            '<TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks>').replace('</Project>',
            '<ItemGroup Condition="&apos;$(TargetFramework)&apos; == &apos;net10.0&apos;"><Compile Remove="LongDirectoryPrefix/Sources/Source00.cs" /></ItemGroup></Project>'))
        self.sync()
        self.assertIn('"LongDirectoryPrefix/Sources/*.cs"', (self.root / "graph.generated.bzl").read_text())
        variants = json.loads((self.root / "graph.generated.json").read_text())["Projects"]["App.csproj"]["Configurations"]
        selected = {variant["Properties"].get("TargetFramework", ""): variant["Inputs"] for variant in variants}
        source = "LongDirectoryPrefix/Sources/Source00.cs"
        self.assertNotIn(source, selected["net10.0"])
        self.assertIn(source, selected["net10.0-windows"])

    def test_reviewed_compile_globs_keep_generated_files_stable(self):
        directory = self.source_group()
        defaults = {"preparedRestore": True, "evaluationReuseInputs": ["@(Compile)"],
                    "compileGlobs": ["LongDirectoryPrefix/Sources/*.cs"]}
        self.sync({"projectDefaults": defaults})
        before = {name: (self.root / name).read_bytes() for name in ["graph.generated.bzl", "graph.generated.json"]}
        contract = json.loads(before["graph.generated.json"])
        self.assertEqual(contract["Version"], 11)
        self.assertEqual(contract["EvaluationReuseGlobs"], defaults["compileGlobs"])
        self.assertEqual(contract["EvaluationReuseInputs"], ["Program.cs"])
        selected = contract["Projects"]["App.csproj"]["Configurations"][0]
        self.assertEqual(selected["CompileGlobs"], defaults["compileGlobs"])
        self.assertFalse(any(path.startswith("LongDirectoryPrefix/") for path in selected["Inputs"]))
        self.assertIn('compile_globs = ["LongDirectoryPrefix/Sources/*.cs"]', before["graph.generated.bzl"].decode())
        (directory / "Added.cs").write_text("public class Added {}")
        self.sync({"projectDefaults": defaults}, flags=["--check"])
        (directory / "Added.cs").rename(directory / "Renamed.cs")
        self.sync({"projectDefaults": defaults}, flags=["--check"])
        for source in directory.glob("*.cs"):
            source.unlink()
        directory.rmdir()
        self.sync({"projectDefaults": defaults}, flags=["--check"])
        for name, content in before.items():
            self.assertEqual((self.root / name).read_bytes(), content)

    def test_root_compile_glob_can_retain_an_empty_reviewed_inventory(self):
        defaults = {"preparedRestore": True, "evaluationReuseInputs": ["@(Compile)"], "compileGlobs": ["*.cs"]}
        (self.root / "BUILD.bazel").write_text('exports_files([])')
        self.sync({"projectDefaults": defaults})
        contract = json.loads((self.root / "graph.generated.json").read_text())
        self.assertEqual(contract["EvaluationReuseInputs"], [])
        self.assertEqual(contract["EvaluationReuseGlobs"], ["*.cs"])
        (self.root / "Extra.cs").write_text("public class Extra {}")
        self.sync({"projectDefaults": defaults}, flags=["--check"])

    def test_compile_globs_require_exact_authored_compile_only_sets(self):
        directory = self.source_group()
        mappings = {"projectDefaults": {"compileGlobs": ["LongDirectoryPrefix/Sources/*.cs"]}}
        project = self.root / "App.csproj"
        for item in ['<Compile Remove="LongDirectoryPrefix/Sources/Source00.cs" />',
                     '<AdditionalFiles Include="LongDirectoryPrefix/Sources/*.cs" />']:
            project.write_text(self.project.replace('</Project>', '<ItemGroup>' + item + '</ItemGroup></Project>'))
            self.assertIn("Compile-only", self.sync(mappings, success=False))
        project.write_text(self.project)
        (directory / ".Hidden.cs").write_text("public class Hidden {}")
        self.assertIn("Compile-only", self.sync(mappings, success=False))
        (directory / ".Hidden.cs").unlink()
        original = directory / "Source00.cs"
        original.rename(directory / "source.txt")
        original.symlink_to("source.txt")
        self.assertIn("Compile-only", self.sync(mappings, success=False))
        original.unlink()
        original.write_text("public class Source00 {}")
        for pattern in ["../*.cs", "LongDirectoryPrefix/**/Nested/*.cs", "obj/*.cs", "LongDirectoryPrefix/Source?.cs"]:
            self.assertIn("workspace-relative", self.sync({"projectDefaults": {"compileGlobs": [pattern]}}, success=False))
        self.assertIn("distinct", self.sync({"projectDefaults": {"compileGlobs": ["*.cs", "*.cs"]}}, success=False))

    def test_recursive_compile_globs_track_new_directories(self):
        directory = self.source_group()
        mappings = {"projectDefaults": {"preparedRestore": True, "evaluationReuseInputs": ["@(Compile)"],
                                        "compileGlobs": ["LongDirectoryPrefix/**/*.cs"]}}
        self.sync(mappings)
        before = {name: (self.root / name).read_bytes() for name in ["graph.generated.bzl", "graph.generated.json"]}
        nested = directory / "New" / "Deep"
        nested.mkdir(parents=True)
        (nested / "Added.cs").write_text("public class Added {}")
        self.sync(mappings, flags=["--check"])
        moved = directory.parent / "Moved"
        moved.mkdir()
        (nested / "Added.cs").rename(moved / "Renamed.cs")
        self.sync(mappings, flags=["--check"])
        (moved / "Renamed.cs").unlink()
        moved.rmdir()
        self.sync(mappings, flags=["--check"])
        for name, content in before.items():
            self.assertEqual((self.root / name).read_bytes(), content)
        (nested / "BUILD.bazel").write_text('exports_files([])')
        self.assertIn("Bazel package", self.sync(mappings, success=False))
        (nested / "BUILD.bazel").unlink()
        nested.rmdir()
        nested.symlink_to(directory, target_is_directory=True)
        self.assertIn("directory link", self.sync(mappings, success=False))

    def test_root_recursive_glob_excludes_output_and_hidden_directories(self):
        (self.root / "BUILD.bazel").write_text('exports_files([])')
        (self.root / "App.csproj").write_text(self.project.replace('</Project>',
            '<ItemGroup><Compile Remove="bazel-*/**/*.cs" /></ItemGroup></Project>'))
        (self.root / "bazel-Named.cs").write_text("public class BazelNamed {}")
        mappings = {"projectDefaults": {"compileGlobs": ["**/*.cs"]}}
        self.sync(mappings)
        (self.root / "bin").mkdir()
        (self.root / "obj").mkdir()
        (self.root / ".hidden").mkdir()
        for directory in ["bin", "obj", ".hidden"]:
            (self.root / directory / "Ignored.cs").write_text("#error Ignored")
        (self.root / "bazel-output").symlink_to(self.root / "bin", target_is_directory=True)
        self.sync(mappings, flags=["--check"])
        # Arbitrary owned output roots are rejected, even before they exist.
        (self.root / "App.csproj").write_text((self.root / "App.csproj").read_text().replace("</PropertyGroup>",
            "<BaseIntermediateOutputPath>generated/</BaseIntermediateOutputPath></PropertyGroup>"))
        self.assertIn("owned output", self.sync(mappings, success=False))

    def test_recursive_globs_preserve_bazel_prefixed_source_files_in_private_views(self):
        (self.root / "bazel-Named.cs").write_text("public class BazelNamed {}")
        manifest = self.root / "inputs.json"
        manifest.write_text(json.dumps({"inputs": [], "packages": [], "packageLock": None}))
        mappings = {"projectDefaults": {"compileGlobs": ["**/*.cs"]}}
        flags = ["--inputs", str(manifest), "--runfiles", str(self.root)]
        self.sync(mappings, flags=flags)
        self.sync(mappings, flags=flags + ["--check"])
        self.sync(mappings, flags=flags + ["--package-build"])
        self.sync(mappings, flags=flags + ["--package-build", "--check"])

    def test_compile_globs_remain_configuration_specific(self):
        self.source_group()
        (self.root / "App.csproj").write_text(self.project.replace('<TargetFramework>net10.0</TargetFramework>',
            '<TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks>').replace('</Project>',
            '<ItemGroup Condition="&apos;$(TargetFramework)&apos; == &apos;net10.0&apos;"><Compile Remove="LongDirectoryPrefix/Sources/Source00.cs" /></ItemGroup></Project>'))
        mappings = {"projects": {"App.csproj": {"frameworkOverrides": {"net10.0-windows":
                    {"compileGlobs": ["LongDirectoryPrefix/Sources/*.cs"]}}}}}
        self.sync(mappings)
        variants = json.loads((self.root / "graph.generated.json").read_text())["Projects"]["App.csproj"]["Configurations"]
        selected = {variant["Properties"].get("TargetFramework", ""): variant for variant in variants}
        self.assertNotIn("CompileGlobs", selected["net10.0"])
        self.assertEqual(selected["net10.0-windows"]["CompileGlobs"], ["LongDirectoryPrefix/Sources/*.cs"])
        self.assertNotIn("LongDirectoryPrefix/Sources/Source00.cs", selected["net10.0-windows"]["Inputs"])

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

    def test_complete_compiler_inventory_requires_review(self):
        binding = {'compilerReferencesComplete': True}
        mapping = {'projects': {'App.csproj': binding}}
        self.assertIn('reviewed reference boundary', self.sync(mapping, success=False))
        binding['referenceBoundary'] = True
        self.sync(mapping)
        contract = json.loads((self.root / 'graph.generated.json').read_text())
        self.assertEqual(contract['Version'], 10)
        self.assertTrue(contract['Projects']['App.csproj']['Configurations'][0]['CompilerReferencesComplete'])

    def test_resolved_compiler_inputs_use_private_qualification_build(self):
        library = self.root / 'Library'
        library.mkdir()
        (library / 'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
        (library / 'Code.cs').write_text('public class Library {}')
        (self.root / 'App.csproj').write_text(self.project.replace('</Project>', '<ItemGroup><Compile Remove="Library/**/*.cs" /><ProjectReference Include="Library/Library.csproj" /></ItemGroup></Project>'))
        (self.root / 'Program.cs').write_text('System.Console.WriteLine(new Library());')
        self.assertIn('--package-build', self.sync(flags=['--resolve-references'], success=False))
        flags = ['--package-build', '--resolve-references']
        self.sync(flags=flags)
        contract = json.loads((self.root / 'graph.generated.json').read_text())
        self.assertEqual(contract['Version'], 10)
        app = contract['Projects']['App.csproj']['Configurations'][0]
        self.assertTrue(app['CompilerReferencesComplete'])
        self.assertEqual(app['CompilerReferences'], {'Library/Library.csproj': 'Library/obj/Release/net10.0/ref/Library.dll'})
        self.assertEqual(app['DependencyCopies']['bin/Release/net10.0/Library.dll'], 'Library/bin/Release/net10.0/Library.dll')
        self.assertFalse((self.root / 'bin').exists())
        self.assertFalse((library / 'obj').exists())
        self.sync(flags=flags + ['--check'])
        before = (self.root / 'graph.generated.json').read_bytes()
        (library / 'Code.cs').write_text('invalid C#')
        self.assertIn('qualification Build failed', self.sync(flags=flags, success=False))
        self.assertEqual((self.root / 'graph.generated.json').read_bytes(), before)

    def test_resolved_compiler_inputs_reject_conflicting_manual_selection(self):
        library = self.root / 'Library'
        library.mkdir()
        (library / 'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
        (library / 'Code.cs').write_text('public class Library {}')
        (self.root / 'App.csproj').write_text(self.project.replace('</Project>', '<ItemGroup><Compile Remove="Library/**/*.cs" /><ProjectReference Include="Library/Library.csproj" /></ItemGroup></Project>'))
        (self.root / 'Program.cs').write_text('System.Console.WriteLine(new Library());')
        mapping = {'projects': {'App.csproj': {'referenceBoundary': True, 'compilerReferences': {'Library/Library.csproj': 'Library/bin/Release/net10.0/Library.dll'}}}}
        self.assertIn('differ from SDK selection', self.sync(mapping, flags=['--package-build', '--resolve-references'], success=False))

    def test_resolved_compiler_inputs_select_multi_target_configuration(self):
        library = self.root / 'Library'
        library.mkdir()
        (library / 'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFrameworks>net10.0-windows;net10.0</TargetFrameworks></PropertyGroup></Project>')
        (library / 'Code.cs').write_text('public class Library {}')
        (self.root / 'App.csproj').write_text(self.project.replace('</Project>', '<ItemGroup><Compile Remove="Library/**/*.cs" /><ProjectReference Include="Library/Library.csproj" /></ItemGroup></Project>'))
        (self.root / 'Program.cs').write_text('System.Console.WriteLine(new Library());')
        self.sync(flags=['--package-build', '--resolve-references'])
        contract = json.loads((self.root / 'graph.generated.json').read_text())
        app = contract['Projects']['App.csproj']['Configurations'][0]
        self.assertEqual(app['CompilerReferences'], {'Library/Library.csproj': 'Library/obj/Release/net10.0/ref/Library.dll'})
        self.assertEqual(len(contract['Projects']['Library/Library.csproj']['Configurations']), 3)

    def test_qualification_rejects_input_mutation_without_touching_sources(self):
        project = self.project.replace('</Project>', '<Target Name="Mutate" BeforeTargets="CoreCompile"><WriteLinesToFile File="Program.cs" Lines="System.Console.WriteLine(2)%3B" Overwrite="true" /></Target></Project>')
        (self.root / 'App.csproj').write_text(project)
        mapping = {'projectDefaults': {'referenceBoundary': True, 'documents': {'App.csproj': {'sha256': hashlib.sha256(project.encode()).hexdigest(), 'targets': ['Mutate'], 'tasks': [], 'inputs': []}}}}
        original = (self.root / 'Program.cs').read_bytes()
        self.assertIn('modified a declared input', self.sync(mapping, flags=['--package-build', '--resolve-references'], success=False))
        self.assertEqual((self.root / 'Program.cs').read_bytes(), original)
        self.assertFalse((self.root / 'graph.generated.json').exists())

    def test_qualification_rejects_outputs_outside_private_workspace(self):
        outside = tempfile.TemporaryDirectory(prefix='graph-sync-output-')
        self.addCleanup(outside.cleanup)
        project = self.project.replace('</PropertyGroup>', '<OutputPath>' + outside.name + '/products/</OutputPath></PropertyGroup>')
        (self.root / 'App.csproj').write_text(project)
        self.sync(flags=['--package-build', '--resolve-references'], success=False)
        self.assertFalse((Path(outside.name) / 'products').exists())
        self.assertFalse((self.root / 'graph.generated.json').exists())

    def test_compiler_file_must_be_declared_for_its_consumer(self):
        hidden = tempfile.TemporaryDirectory(prefix='graph-sync-hidden-')
        self.addCleanup(hidden.cleanup)
        source = Path(hidden.name)
        (source / 'empty').mkdir()
        (source / 'Hidden.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
        (source / 'Code.cs').write_text('public class Hidden {}')
        built = subprocess.run([str(SDK / 'dotnet'), 'build', str(source / 'Hidden.csproj'), '-c', 'Release', '-p:UseSharedCompilation=false', '-p:NuGetAudit=false', '-p:RestoreSources=' + str(source / 'empty')], capture_output=True, text=True)
        self.assertEqual(built.returncode, 0, built.stdout + built.stderr)
        library = self.root / 'Library'
        library.mkdir()
        (library / 'Library.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
        (library / 'Code.cs').write_text('public class Library {}')
        shutil.copyfile(source / 'bin/Release/net10.0/Hidden.dll', library / 'Hidden.dll')
        project = self.project.replace('</Project>', '<ItemGroup><Compile Remove="Library/**/*.cs" /><None Remove="Library/**" /><ProjectReference Include="Library/Library.csproj" /></ItemGroup><Target Name="InjectHidden" BeforeTargets="FindReferenceAssembliesForReferences"><ItemGroup><ReferencePath Include="Library/Hidden.dll"><Aliases>hidden</Aliases></ReferencePath></ItemGroup></Target></Project>')
        (self.root / 'App.csproj').write_text(project)
        mapping = {'projectDefaults': {'referenceBoundary': True}, 'projects': {'App.csproj': {'documents': {'App.csproj': {'sha256': hashlib.sha256(project.encode()).hexdigest(), 'targets': ['InjectHidden'], 'tasks': [], 'inputs': []}}}}}
        self.assertIn('Undeclared resolved compiler input', self.sync(mapping, flags=['--package-build', '--resolve-references'], success=False))
        mapping['projects']['App.csproj']['documents']['App.csproj']['inputs'] = ['Library/Hidden.dll']
        self.sync(mapping, flags=['--package-build', '--resolve-references'])

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
