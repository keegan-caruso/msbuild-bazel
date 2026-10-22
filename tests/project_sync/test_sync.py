"""The public sync executable has one graph backend and a fail-closed schema."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile
import unittest
import zipfile
from unittest.mock import patch

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

    def test_opt_in_profiling_preserves_declarations(self):
        command = [str(SDK / 'dotnet'), str(RUNNER), str(self.root), str(SDK / 'sdk/10.0.400'), 'App.csproj']
        expected = None
        for enabled in [None, '1']:
            environment = dict(os.environ, DOTNET_ROOT=str(SDK))
            environment.pop('RULES_MSBUILD_SYNC_PROFILE', None)
            if enabled:
                environment['RULES_MSBUILD_SYNC_PROFILE'] = enabled
            result = subprocess.run(command, capture_output=True, text=True, env=environment)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            phases = [json.loads(line.removeprefix('PROJECT_SYNC_PROFILE ')) for line in result.stderr.splitlines()
                if line.startswith('PROJECT_SYNC_PROFILE ')]
            self.assertEqual(bool(phases), enabled == '1')
            self.assertTrue(all(row['seconds'] >= 0 for row in phases))
            current = [(self.root / name).read_bytes() for name in ['graph.generated.json', 'graph.generated.bzl']]
            if expected is not None:
                self.assertEqual(current, expected)
            expected = current

    def test_prepared_publication_checks_both_outputs_and_rejects_links(self):
        self.sync()
        with tempfile.TemporaryDirectory(prefix='prepared-sync-') as directory:
            prepared = Path(directory)
            expected = {}
            for name in ['graph.generated.json', 'graph.generated.bzl']:
                expected[name] = (self.root / name).read_bytes()
                (prepared / name).write_bytes(expected[name])

            def publish(*flags):
                return subprocess.run([str(SDK / 'dotnet'), str(RUNNER), 'publish', str(prepared), str(self.root), *flags],
                    capture_output=True, text=True)

            self.assertEqual(publish('--check').returncode, 0)
            (self.root / 'graph.generated.bzl').write_text('# authored file\n')
            result = publish()
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Refusing to overwrite', result.stderr)
            self.assertEqual((self.root / 'graph.generated.json').read_bytes(), expected['graph.generated.json'])
            (self.root / 'graph.generated.bzl').unlink()
            (self.root / 'graph.generated.bzl').symlink_to(prepared / 'graph.generated.bzl')
            self.assertIn('Refusing to replace a linked', publish().stderr)
            (self.root / 'graph.generated.bzl').unlink()
            self.assertEqual(publish().returncode, 0)
            self.assertIn('accepts only --check', publish('--framework', 'net8.0').stderr)
            (prepared / 'graph.generated.bzl').write_text('# invalid preparation\n')
            self.assertIn('Invalid prepared sync outputs', publish().stderr)
            for name, contents in expected.items():
                self.assertEqual((self.root / name).read_bytes(), contents)

    def test_prepared_staging_rejects_path_escape_and_overlaps(self):
        manifest = self.root / 'stage.json'
        for paths in [['../outside'], ['same', 'same'], ['parent', 'parent/child']]:
            manifest.write_text(json.dumps({'sources': [{'path': path, 'file': str(self.root / 'Program.cs')} for path in paths], 'runfiles': []}))
            with tempfile.TemporaryDirectory(prefix='sync-stage-') as directory:
                result = subprocess.run([str(SDK / 'dotnet'), str(RUNNER), 'stage', str(manifest), directory], capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_prepared_tree_materializes_projection_and_rejects_authored_links(self):
        relative = Path('bazel-out/bin/producer')
        original, projected = self.root / 'execroot' / relative, self.root / relative
        for root in [original, projected]:
            (root / 'nested').mkdir(parents=True)
        for name in ['Code.cs', 'nested/metadata.txt']:
            (original / name).write_text('declared artifact')
            (projected / name).symlink_to(original / name)
        manifest = self.root / 'tree-stage.json'
        manifest.write_text(json.dumps({'sources': [], 'runfiles': [{'path': 'producer', 'file': str(relative), 'tree': True},
            {'path': 'single.txt', 'file': str(original / 'nested/metadata.txt'), 'tree': True}]}))

        def stage():
            destination = Path(tempfile.mkdtemp(dir=self.root))
            result = subprocess.run([str(SDK / 'dotnet'), str(RUNNER), 'stage', str(manifest), str(destination)],
                cwd=self.root, capture_output=True, text=True)
            return result, destination / 'runfiles/producer'

        result, staged = stage()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in ['Code.cs', 'nested/metadata.txt']:
            self.assertEqual((staged / name).read_text(), 'declared artifact')
            self.assertFalse((staged / name).is_symlink())
        self.assertEqual((staged.parent / 'single.txt').read_text(), 'declared artifact')
        self.assertFalse((staged.parent / 'single.txt').is_symlink())
        outside = self.root / 'outside.txt'
        outside.write_text('undeclared')
        (original / 'Code.cs').unlink()
        (original / 'Code.cs').symlink_to(outside)
        self.assertIn('tree symlinks are unsupported', stage()[0].stderr)
        (original / 'Code.cs').unlink()
        (original / 'Code.cs').write_text('declared artifact')
        (projected / 'Code.cs').unlink()
        (projected / 'Code.cs').symlink_to(outside)
        self.assertIn('tree symlinks are unsupported', stage()[0].stderr)
        (projected / 'Code.cs').unlink()
        (projected / 'Code.cs').symlink_to(original / 'Code.cs')
        directory = self.root / 'outside-directory'
        (original / 'nested').rename(directory)
        (original / 'nested').symlink_to(directory, target_is_directory=True)
        self.assertIn('tree directory symlinks are unsupported', stage()[0].stderr)

    def test_analyzer_discovery_stays_inside_workspace(self):
        parent = self.root
        self.root = parent / 'workspace'
        self.root.mkdir()
        (self.root / 'App.csproj').write_text(self.project)
        (self.root / 'Program.cs').write_text('System.Console.WriteLine(1);')
        (parent / '.editorconfig').write_text('[*.cs]\ndotnet_diagnostic.CA1822.severity = none\n')
        (parent / '.globalconfig').write_text('is_global = true\n')
        (self.root / '.editorconfig').write_text('root = true\n[*.cs]\ndotnet_diagnostic.CA1822.severity = error\n')
        (self.root / '.globalconfig').write_text('is_global = true\n')
        (self.root / 'Nested').mkdir()
        (self.root / 'Nested/Code.cs').write_text('public class Nested {}')
        (self.root / 'Nested/.editorconfig').write_text('[*.cs]\ndotnet_diagnostic.CA1822.severity = warning\n')
        self.sync()
        contract = json.loads((self.root / 'graph.generated.json').read_text())
        inputs = contract['Projects']['App.csproj']['Configurations'][0]['Inputs']
        self.assertTrue({'.editorconfig', '.globalconfig', 'Nested/.editorconfig'} <= set(inputs))
        self.assertFalse(any(path.startswith('../') for path in inputs))
        self.sync(flags=['--check'])
        # An authored outside read must still fail even if SDK discovery finds it.
        (self.root / 'App.csproj').write_text(self.project.replace('</Project>',
            '<ItemGroup><EditorConfigFiles Include="../.editorconfig" /></ItemGroup></Project>'))
        self.assertIn('outside workspace', self.sync(success=False))

    def test_assembly_references_require_explicit_producer_labels(self):
        project = self.project.replace('</Project>', '<ItemGroup><Reference Include="System.IO.Pipelines" HintPath="inputs/Pipelines.dll" /></ItemGroup></Project>')
        (self.root / "App.csproj").write_text(project)
        self.assertIn("label-bound assembly references", self.sync(success=False))
        with tempfile.TemporaryDirectory(prefix="graph-sync-producer-") as directory:
            producer = Path(directory)
            # Use the downloaded SDK's matching runtime, without hard-coding its patch.
            assembly = next((SDK / "shared/Microsoft.NETCore.App").glob("*/System.IO.Pipelines.dll"))
            shutil.copyfile(assembly, producer / "Pipelines.dll")
            manifest = producer / "inputs.json"
            manifest.write_text(json.dumps({"inputs": [{"path": "inputs/Pipelines.dll", "label": "@producer//:assembly", "runfile": "Pipelines.dll"}], "packages": [], "packageLock": None}))
            flags = ["--inputs", str(manifest), "--runfiles", str(producer)]
            self.sync(flags=flags)
            contract = json.loads((self.root / "graph.generated.json").read_text())
            selected = contract["Projects"]["App.csproj"]["Configurations"][0]
            self.assertIn("inputs/Pipelines.dll", selected["Inputs"])
            generated = (self.root / "graph.generated.bzl").read_text()
            self.assertIn('"@producer//:assembly":"inputs/Pipelines.dll"', generated)
            self.sync(flags=flags + ["--check"])
            # MSBuild also accepts a file path directly in Reference Include.
            (self.root / "App.csproj").write_text(project.replace('Include="System.IO.Pipelines" HintPath="inputs/Pipelines.dll"', 'Include="inputs/Pipelines.dll"'))
            self.sync(flags=flags)
            contract = json.loads((self.root / "graph.generated.json").read_text())
            self.assertIn("inputs/Pipelines.dll", contract["Projects"]["App.csproj"]["Configurations"][0]["Inputs"])
            self.sync(flags=flags + ["--check"])
            self.sync(flags=flags + ["--package-build", "--resolve-references"])
            # A label for another file does not authorize this reference path.
            manifest.write_text(manifest.read_text().replace("inputs/Pipelines.dll", "inputs/Other.dll"))
            self.assertIn("label-bound assembly references", self.sync(flags=flags, success=False))

    def test_removed_mode_flag_is_rejected(self):
        self.assertIn("Unknown", self.sync(flags=["--graph"], success=False))

    def test_configuration_is_direct(self):
        self.sync(flags=["--configuration", "Debug"])
        self.assertEqual(json.loads((self.root / "graph.generated.json").read_text())["Properties"]["Configuration"], "Debug")

    def test_reference_tree_retains_one_producer_and_rejects_unsafe_members(self):
        (self.root / "App.csproj").write_text(self.project.replace('</Project>',
            '<ItemGroup><Reference Include="System.IO.Pipelines" HintPath="artifacts/bin/ref/Pipelines.dll" />'
            '<Reference Include="System.Text.Json" HintPath="artifacts/bin/ref/nested/Json.dll" /></ItemGroup></Project>'))
        with tempfile.TemporaryDirectory(prefix="graph-sync-tree-") as directory:
            producer = Path(directory)
            tree = producer / 'tree'
            (tree / 'nested').mkdir(parents=True)
            runtime = next((SDK / "shared/Microsoft.NETCore.App").glob('*/System.IO.Pipelines.dll')).parent
            shutil.copyfile(runtime / 'System.IO.Pipelines.dll', tree / 'Pipelines.dll')
            shutil.copyfile(runtime / 'System.Text.Json.dll', tree / 'nested/Json.dll')
            manifest = producer / 'inputs.json'
            manifest.write_text(json.dumps({'inputs': [{'path': 'artifacts/bin/ref', 'label': '@producer//:tree',
                'runfile': 'tree', 'directory': True}], 'packages': [], 'packageLock': None}))
            flags = ['--inputs', str(manifest), '--runfiles', str(producer)]
            self.sync(flags=flags)
            generated = (self.root / 'graph.generated.bzl').read_text()
            self.assertIn('"@producer//:tree":"artifacts/bin/ref"', generated)
            contract = json.loads((self.root / 'graph.generated.json').read_text())
            self.assertEqual(contract['Version'], 12)
            self.assertEqual(contract['InputTrees'], {'artifacts/bin/ref': {'Files': ['artifacts/bin/ref/Pipelines.dll', 'artifacts/bin/ref/nested/Json.dll'], 'Directories': ['artifacts/bin/ref/nested']}})
            self.assertTrue(set(contract['InputTrees']['artifacts/bin/ref']['Files']) <= set(contract['SharedInputs']))
            self.assertNotIn('"artifacts/bin/ref/Pipelines.dll"', generated)
            self.sync(flags=flags + ['--check'])
            self.sync(flags=flags + ['--package-build', '--resolve-references'])
            # Runfiles roots are links; internal members must still be regular.
            linked = producer / 'linked'
            linked.symlink_to(tree, target_is_directory=True)
            manifest.write_text(manifest.read_text().replace('"tree"', '"linked"'))
            self.sync(flags=flags + ['--package-build', '--resolve-references'])
            # The producer edge cannot mask an authored file or escape its tree.
            (self.root / 'artifacts/bin/ref').mkdir(parents=True)
            (self.root / 'artifacts/bin/ref/authored.txt').write_text('owned')
            self.assertIn('colliding source input', self.sync(flags=flags, success=False))
            shutil.rmtree(self.root / 'artifacts/bin/ref')
            (tree / 'nested/escape').symlink_to(producer / 'inputs.json')
            self.assertIn('tree symlinks are unsupported', self.sync(flags=flags, success=False))
            (tree / 'nested/escape').unlink()
            (tree / '.nuget').mkdir()
            (tree / '.nuget/injected').write_text('reserved')
            self.assertIn('reserved sync input', self.sync(flags=flags, success=False))

    def test_build_only_producers_separate_restore_content_and_keep_layout(self):
        with tempfile.TemporaryDirectory(prefix='sync-build-only-') as directory:
            base = Path(directory)
            tree = base / 'tree'
            (tree / 'empty').mkdir(parents=True)
            (tree / 'data.txt').write_text('first build content')
            (base / 'single.txt').write_text('single build content')
            manifest = base / 'inputs.json'
            manifest.write_text(json.dumps({'inputs': [
                {'path': 'producer', 'label': '@producer//:tree', 'runfile': 'tree', 'directory': True, 'buildOnly': True},
                {'path': 'single.txt', 'label': '@producer//:file', 'runfile': 'single.txt', 'buildOnly': True}], 'packages': []}))
            flags = ['--inputs', str(manifest), '--runfiles', str(base)]
            self.assertIn('requires preparedRestore', self.sync(flags=flags, success=False))
            mapping = {'projectDefaults': {'preparedRestore': True}}
            self.sync(mapping, flags=flags)
            contract = json.loads((self.root / 'graph.generated.json').read_text())
            self.assertEqual(contract['Version'], 13)
            self.assertEqual(contract['Restore']['BuildInputs'], ['producer/data.txt', 'single.txt'])
            self.assertFalse(set(contract['Restore']['Inputs']) & set(contract['Restore']['BuildInputs']))
            self.assertEqual(contract['InputTrees']['producer']['Directories'], ['producer/empty'])
            self.assertIn('producer', contract['InputDirectories'])
            text = (self.root / 'graph.generated.bzl').read_text()
            restore, build = text.split('    msbuild_graph_restore(', 1)[1].split('    msbuild_graph(', 1)
            self.assertNotIn('@producer//', restore)
            self.assertIn('@producer//:tree', build)
            self.assertIn('@producer//:file', build)
            generated = {name: (self.root / name).read_bytes() for name in ['graph.generated.json', 'graph.generated.bzl']}
            for name in generated:
                (self.root / name).unlink()
            runner = ROOT / 'tools/GraphBuild/bin/Release/net10.0/GraphBuild.dll'
            payload = base / 'contract.json'
            prepared = base / 'prepared'
            report = base / 'report.json'
            command = [str(SDK / 'dotnet'), str(runner)]
            environment = dict(os.environ, DOTNET_ROOT=str(SDK))
            for case in ['version', 'duplicate', 'definition', 'undeclared']:
                invalid = json.loads(json.dumps(contract))
                if case == 'version':
                    invalid['Version'] = 12
                elif case == 'duplicate':
                    invalid['Restore']['BuildInputs'].append('single.txt')
                elif case == 'definition':
                    invalid['Restore']['BuildInputs'].append('App.csproj')
                else:
                    invalid['Restore']['BuildInputs'].append('missing.txt')
                payload.write_text(json.dumps(invalid))
                result = subprocess.run(command + ['prepare', str(self.root), str(payload), str(report), str(prepared)],
                    env=environment, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0, case)
                self.assertIn('Build-only Restore inputs', result.stderr)
                self.assertFalse((self.root / 'producer/data.txt').exists())
                self.assertFalse(prepared.exists())
            payload.write_text(json.dumps(contract))
            result = subprocess.run(command + ['prepare', str(self.root), str(payload), str(report), str(prepared)],
                env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((self.root / 'producer/data.txt').read_bytes(), b'')
            self.assertEqual((self.root / 'single.txt').read_bytes(), b'')
            # The build receives real bytes, while the same verified Restore artifact applies.
            shutil.copy2(tree / 'data.txt', self.root / 'producer/data.txt')
            shutil.copy2(base / 'single.txt', self.root / 'single.txt')
            environment['RULES_MSBUILD_GRAPH_PREPARED_RESTORE'] = str(prepared)
            for content in ['first content', 'changed content']:
                (self.root / 'producer/data.txt').write_text(content)
                for name in ['bin', 'obj/Release']:
                    shutil.rmtree(self.root / name, ignore_errors=True)
                result = subprocess.run(command + ['action', str(self.root), str(payload), str(report), str(base / 'cache')],
                    env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(json.loads(report.read_text())['misses'], 1)
            shutil.rmtree(self.root / 'producer')
            (self.root / 'single.txt').unlink()
            for name in ['bin', 'obj']:
                shutil.rmtree(self.root / name, ignore_errors=True)
            for name, content in generated.items():
                (self.root / name).write_bytes(content)
            # Byte changes do not change Restore's key or structural declaration.
            (tree / 'data.txt').write_text('second build content')
            (base / 'single.txt').write_text('second single content')
            self.sync(mapping, flags=flags + ['--check'])
            # Membership changes still require review; they affect Restore layout.
            (tree / 'added.txt').write_text('new member')
            self.sync(mapping, flags=flags + ['--check'], success=False)
            self.sync(mapping, flags=flags)
            mapping['projectDefaults']['restoreInputs'] = ['producer/data.txt']
            self.assertIn('explicit Restore input', self.sync(mapping, flags=flags, success=False))
            mapping['projectDefaults'].pop('restoreInputs')
            self.assertIn('package task input', self.sync(mapping, flags=flags + ['--package-input', 'producer/data.txt'], success=False))
            # Imported definitions cannot be declared content-independent.
            (base / 'single.txt').write_text('<Project><PropertyGroup><Extra>true</Extra></PropertyGroup></Project>')
            (self.root / 'App.csproj').write_text(self.project.replace('</Project>', '<Import Project="single.txt" /></Project>'))
            self.assertIn('definition', self.sync(mapping, flags=flags, success=False))

    def test_tree_contract_guards_membership_and_hashes_bytes(self):
        with tempfile.TemporaryDirectory(prefix='graph-tree-cache-') as directory:
            base = Path(directory)
            tree = base / 'producer'
            (tree / 'empty').mkdir(parents=True)
            (tree / 'data.txt').write_text('one')
            (base / 'empty').mkdir()
            manifest = base / 'inputs.json'
            manifest.write_text(json.dumps({'inputs': [{'path': 'inputs', 'label': '@producer//:tree',
                'runfile': 'producer', 'directory': True}, {'path': 'empty-tree', 'label': '@producer//:empty',
                'runfile': 'empty', 'directory': True}], 'packages': [], 'packageLock': None}))
            self.sync(flags=['--inputs', str(manifest), '--runfiles', str(base)])
            contract = base / 'contract.json'
            (self.root / 'graph.generated.json').rename(contract)
            (self.root / 'graph.generated.bzl').unlink()
            data = json.loads(contract.read_text())
            self.assertEqual(data['InputTrees']['inputs']['Directories'], ['inputs/empty'])
            self.assertFalse((self.root / 'NuGet.Config').exists())
            self.assertFalse(any('NuGet.Config' in node['Inputs'] for project in data['Projects'].values() for node in project['Configurations']))
            self.assertEqual(data['InputTrees']['empty-tree'], {'Files': [], 'Directories': []})
            self.assertIn('empty-tree', data['InputDirectories'])
            shutil.copytree(tree, self.root / 'inputs')
            (self.root / 'empty-tree').mkdir()
            graph_runner = ROOT / 'tools/GraphBuild/bin/Release/net10.0/GraphBuild.dll'
            def build(failure=None):
                # Clear products so each row must run the project-cache decision.
                for path in ['bin', 'obj']:
                    shutil.rmtree(self.root / path, ignore_errors=True)
                result = subprocess.run([str(SDK / 'dotnet'), str(graph_runner), 'action', str(self.root),
                    str(contract), str(base / 'report.json'), str(base / 'cache')], capture_output=True, text=True,
                    env=dict(os.environ, DOTNET_ROOT=str(SDK)))
                self.assertEqual(result.returncode == 0, failure is None, result.stdout + result.stderr)
                if failure:
                    self.assertIn(failure, result.stdout + result.stderr)
                else:
                    return json.loads((base / 'report.json').read_text())
            self.assertEqual(build()['misses'], 1)
            self.assertEqual(build()['hits'], 1)
            # Even a member consumed only by a reviewed task affects cache identity.
            (self.root / 'inputs/data.txt').write_text('two')
            self.assertEqual(build()['misses'], 1)
            (self.root / 'inputs/new.txt').write_text('new')
            build('membership changed; rerun sync')
            (self.root / 'inputs/new.txt').unlink()
            (self.root / 'inputs/new-directory').mkdir()
            build('membership changed; rerun sync')
            (self.root / 'inputs/new-directory').rmdir()
            (self.root / 'inputs/empty').rmdir()
            build('membership changed; rerun sync')

    def test_analyzer_project_reference_uses_implementation(self):
        (self.root / 'Generator').mkdir()
        (self.root / 'Generator/Generator.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
        (self.root / 'Generator/Code.cs').write_text('public class Generator {}')
        (self.root / 'App.csproj').write_text(self.project.replace('</Project>',
            '<ItemGroup><ProjectReference Include="Generator/Generator.csproj" ReferenceOutputAssembly="false" OutputItemType="Analyzer" /></ItemGroup></Project>'))
        self.sync()
        contract=json.loads((self.root / 'graph.generated.json').read_text())
        self.assertGreaterEqual(contract['Version'], 3)
        node=contract['Projects']['App.csproj']['Configurations'][0]
        self.assertEqual(node['ImplementationDependencies'], ['Generator/Generator.csproj'])

    def test_sdk_artifact_only_project_retains_reviewed_outputs(self):
        project=self.project.replace('<Project Sdk="Microsoft.NET.Sdk">', '<Project><Import Project="Sdk.props" Sdk="Microsoft.NET.Sdk" />').replace('</Project>', '<Import Project="Sdk.targets" Sdk="Microsoft.NET.Sdk" /><Target Name="Build"><WriteLinesToFile File="artifact.txt" Lines="produced" Overwrite="true" /></Target></Project>')
        (self.root / 'App.csproj').write_text(project)
        mapping={'entryProperties': {'App.csproj': {'TargetPath': ''}}, 'projects': {'App.csproj': {
            'outputFiles': ['artifact.txt'], 'documents': {'App.csproj': {'sha256': hashlib.sha256(project.encode()).hexdigest(),
            'targets': ['Build'], 'tasks': [], 'inputs': []}}}}}
        self.sync(mapping)
        node=json.loads((self.root / 'graph.generated.json').read_text())['Projects']['App.csproj']['Configurations'][0]
        self.assertEqual(node['OutputDirectories'], [])
        self.assertEqual(node['OutputFiles'], ['artifact.txt'])

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
        self.assertNotIn('BuildInputs', contract['Restore'])
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

    @unittest.skipUnless(os.path.isfile("/usr/bin/bwrap"), "Linux qualification sandbox required")
    def test_qualification_cache_reuses_projects_and_preserves_sdk_inventory(self):
        for name, dependency in [('C', None), ('B', 'C'), ('D', None)]:
            directory = self.root / name
            directory.mkdir()
            reference = '<ItemGroup><ProjectReference Include="../C/C.csproj" /></ItemGroup>' if dependency else ''
            (directory / (name + '.csproj')).write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                '<TargetFramework>net10.0</TargetFramework><GenerateDocumentationFile>true</GenerateDocumentationFile>'
                '<ProduceReferenceAssembly>false</ProduceReferenceAssembly></PropertyGroup>' + reference + '</Project>')
            (directory / 'Code.cs').write_text('public static class ' + name + ' { public static int Value() => 1; }')
        (self.root / 'App.csproj').write_text(self.project.replace('</Project>',
            '<ItemGroup><Compile Remove="B/**;C/**;D/**" /><ProjectReference Include="B/B.csproj" /></ItemGroup></Project>'))
        flags = ['D/D.csproj', '--package-build', '--resolve-references']
        self.sync(flags=flags)
        expected = [(self.root / name).read_bytes() for name in ['graph.generated.json', 'graph.generated.bzl']]
        cache = tempfile.TemporaryDirectory(prefix='qualification-cache-')
        self.addCleanup(cache.cleanup)

        def run(*extra, success=True):
            output = self.sync(flags=flags + ['--qualification-cache', cache.name] + list(extra), success=success)
            reports = [json.loads(line.split(' ', 1)[1]) for line in output.splitlines() if line.startswith('PROJECT_SYNC_CACHE ')]
            return reports[-1] if success else output

        with patch.dict(os.environ, {'RULES_MSBUILD_SYNC_PROFILE': '1'}):
            output = self.sync(flags=flags + ['--qualification-cache', cache.name])
        report = next(json.loads(line.split(' ', 1)[1]) for line in output.splitlines() if line.startswith('PROJECT_SYNC_CACHE '))
        self.assertEqual(report, {'hits': 0, 'misses': 4, 'uncacheable': 0, 'compilations': 4})
        evaluation = next(json.loads(line.split(' ', 1)[1]) for line in output.splitlines() if line.startswith('PROJECT_SYNC_EVALUATION '))
        self.assertEqual(evaluation['workerEvaluations'], 0)
        self.assertEqual([(self.root / name).read_bytes() for name in ['graph.generated.json', 'graph.generated.bzl']], expected)
        self.assertEqual(run('--check'), {'hits': 4, 'misses': 0, 'uncacheable': 0, 'compilations': 0})
        original = (self.root / 'C/Code.cs').read_text()
        (self.root / 'C/Code.cs').write_text(original.replace('=> 1', '=> 2'))
        self.assertEqual(run()['hits'], 1)
        self.assertEqual(run('--check')['compilations'], 0)
        (self.root / 'C/Code.cs').write_text(original.replace('public static int Value()', 'public static int Added() => 3; public static int Value()'))
        self.assertEqual(run()['compilations'], 3)
        (self.root / 'C/Code.cs').write_text(original)
        self.assertEqual(run('--check')['compilations'], 0)
        for name, data in zip(['graph.generated.json', 'graph.generated.bzl'], expected):
            self.assertEqual((self.root / name).read_bytes(), data)
        (self.root / 'C/Code.cs').chmod(0o755)
        self.assertEqual(run()['compilations'], 3)
        (self.root / 'C/Code.cs').chmod(0o644)
        self.assertEqual(run('--check')['compilations'], 0)
        # Shared evaluation inputs affect every project. Failed builds publish nothing.
        props = self.root / 'Directory.Build.props'
        props.write_text('<Project><PropertyGroup><DefineConstants>CHANGED</DefineConstants></PropertyGroup></Project>')
        self.assertEqual(run()['compilations'], 4)
        self.assertEqual(run('--check')['compilations'], 0)
        props.unlink()
        self.assertEqual(run()['compilations'], 0)
        (self.root / 'C/Code.cs').write_text('invalid C#')
        entries = set(Path(cache.name).glob('*/manifest.json'))
        self.assertIn('qualification Build failed', run(success=False))
        self.assertEqual(set(Path(cache.name).glob('*/manifest.json')), entries)
        (self.root / 'C/Code.cs').write_text(original)
        self.assertEqual(run('--check')['compilations'], 0)
        # A relocated source and fresh private build recover the same metadata.
        relocated = Path(tempfile.mkdtemp(prefix='qualification-relocated-'))
        self.addCleanup(shutil.rmtree, relocated)
        for path in self.root.iterdir():
            if path.is_dir():
                shutil.copytree(path, relocated / path.name)
            else:
                shutil.copyfile(path, relocated / path.name)
        prior = self.root
        self.root = relocated
        try:
            self.assertEqual(run('--check')['compilations'], 0)
        finally:
            self.root = prior
        # Verify artifact bytes even when the manifest and metadata are intact.
        artifacts = {path: path.read_bytes() for path in Path(cache.name).glob('*/outputs/**/*.dll')}
        self.assertTrue(artifacts)
        for path, data in artifacts.items():
            path.write_bytes(data + b'corrupt')
        self.assertIn('Corrupt qualification snapshot', run(success=False))
        for path, data in artifacts.items():
            path.write_bytes(data)
        self.assertEqual(run('--check')['compilations'], 0)
        # Inventory is a verified payload too. Corruption preserves both outputs.
        for state in Path(cache.name).glob('*/state.json'):
            state.write_text(state.read_text() + ' ')
        self.assertIn('Corrupt qualification snapshot', run(success=False))
        for name, data in zip(['graph.generated.json', 'graph.generated.bzl'], expected):
            self.assertEqual((self.root / name).read_bytes(), data)

    @unittest.skipUnless(os.path.isfile("/usr/bin/bwrap"), "Linux qualification sandbox required")
    def test_qualification_restore_cache_reviews_contents_but_keeps_membership(self):
        flags = ['--package-build', '--resolve-references']
        self.sync(flags=flags)
        with tempfile.TemporaryDirectory(prefix='qualification-restore-') as directory:
            flags += ['--qualification-cache', directory]
            mapping = {'restoreReuseInputs': ['Program.cs']}

            def run(success=True):
                return self.sync(mapping, flags=flags, success=success)

            self.assertIn('PROJECT_SYNC_RESTORE_CACHE miss', run())
            expected = [(self.root / name).read_bytes() for name in ['graph.generated.json', 'graph.generated.bzl']]
            self.assertIn('PROJECT_SYNC_RESTORE_CACHE hit', run())
            (self.root / 'Program.cs').write_text('System.Console.WriteLine(2);')
            output = run()
            self.assertIn('PROJECT_SYNC_RESTORE_CACHE hit', output)
            self.assertIn('"compilations":1', output)
            self.assertEqual([(self.root / name).read_bytes() for name in ['graph.generated.json', 'graph.generated.bzl']], expected)
            (self.root / 'Added.cs').write_text('public class Added {}')
            self.assertIn('PROJECT_SYNC_RESTORE_CACHE miss', run())
            self.assertIn('PROJECT_SYNC_RESTORE_CACHE hit', run())
            (self.root / 'Added.cs').unlink()
            self.assertIn('PROJECT_SYNC_RESTORE_CACHE hit', run())
            (self.root / 'Program.cs').chmod(0o755)
            self.assertIn('PROJECT_SYNC_RESTORE_CACHE miss', run())
            (self.root / 'Program.cs').chmod(0o644)
            self.assertIn('PROJECT_SYNC_RESTORE_CACHE hit', run())
            # Failed compilation cannot add a prepared Restore entry.
            (self.root / 'Program.cs').write_text('invalid C#')
            (self.root / 'new.txt').write_text('new layout')
            before = set(Path(directory).glob('restore/*/manifest.json'))
            self.assertIn('qualification Build failed', run(success=False))
            self.assertEqual(set(Path(directory).glob('restore/*/manifest.json')), before)
            (self.root / 'new.txt').unlink()
            (self.root / 'Program.cs').write_text('System.Console.WriteLine(2);')
            # Definitions cannot use the content exemption.
            mapping['restoreReuseInputs'] = ['App.csproj']
            self.assertIn('must name authored Compile', run(success=False))
            mapping['restoreReuseInputs'] = ['Program.cs']
            # Verified Restore metadata and products fail closed before publication.
            generated = [(self.root / name).read_bytes() for name in ['graph.generated.json', 'graph.generated.bzl']]
            for path in Path(directory).glob('restore/*/outputs/**/project.assets.json'):
                path.write_text('corrupt')
            self.assertIn('Corrupt Restore snapshot', run(success=False))
            self.assertEqual([(self.root / name).read_bytes() for name in ['graph.generated.json', 'graph.generated.bzl']], generated)

    @unittest.skipUnless(os.path.isfile("/usr/bin/bwrap"), "Linux qualification sandbox required")
    def test_qualification_restore_cache_keeps_custom_restore_inputs(self):
        targets = ('<Project><Target Name="RestoreProbe" BeforeTargets="Restore">'
            '<Message Importance="High" Text="RESTORE_HOOK_RAN" />'
            "<Error Condition=\"'$([System.IO.File]::ReadAllText(`restore-input.txt`))' == 'fail'\" Text=\"RESTORE_INPUT_CHANGED\" />"
            '<MakeDir Directories="obj/empty-restore-product" />'
            '</Target><Target Name="CheckRestoreProduct" BeforeTargets="Build">'
            '<Error Condition="!Exists(&apos;obj/empty-restore-product&apos;)" Text="Lost empty Restore product" />'
            '</Target></Project>')
        (self.root / 'Directory.Build.targets').write_text(targets)
        (self.root / 'restore-input.txt').write_text('pass')
        mapping = {'restoreReuseInputs': ['Program.cs'], 'projectDefaults': {'referenceBoundary': True, 'documents': {'Directory.Build.targets': {
            'sha256': hashlib.sha256(targets.encode()).hexdigest(), 'targets': ['RestoreProbe', 'CheckRestoreProduct'],
            'tasks': [], 'inputs': ['restore-input.txt']}}}}
        with tempfile.TemporaryDirectory(prefix='qualification-restore-hooks-') as directory:
            flags = ['--package-build', '--resolve-references', '--qualification-cache', directory]
            first = self.sync(mapping, flags=flags)
            self.assertIn('RESTORE_HOOK_RAN', first)
            second = self.sync(mapping, flags=flags)
            self.assertIn('PROJECT_SYNC_RESTORE_CACHE hit', second)
            self.assertNotIn('RESTORE_HOOK_RAN', second)
            (self.root / 'restore-input.txt').write_text('fail')
            before = (self.root / 'graph.generated.json').read_bytes()
            self.assertIn('RESTORE_INPUT_CHANGED', self.sync(mapping, flags=flags, success=False))
            self.assertEqual((self.root / 'graph.generated.json').read_bytes(), before)

    @unittest.skipUnless(os.path.isfile("/usr/bin/bwrap"), "Linux qualification sandbox required")
    def test_qualification_restore_cache_keeps_package_sdk_resolution(self):
        (self.root / 'global.json').write_text(json.dumps({'sdk': {'version': '10.0.400'},
            'msbuild-sdks': {'Microsoft.DotNet.Arcade.Sdk': '1.0.0'}}))
        (self.root / 'App.csproj').write_text(self.project.replace('<PropertyGroup>',
            '<Import Project="Sdk.props" Sdk="Microsoft.DotNet.Arcade.Sdk" /><PropertyGroup>', 1))
        (self.root / 'Program.cs').write_text('#if !DECLARED_PACKAGE_SDK\n#error Missing package SDK\n#endif\nSystem.Console.WriteLine(1);')
        with tempfile.TemporaryDirectory(prefix='qualification-package-sdk-') as directory:
            base = Path(directory)
            package = base / 'runfiles/arcade'
            package.mkdir(parents=True)
            archive = package / 'microsoft.dotnet.arcade.sdk.1.0.0.nupkg'
            with zipfile.ZipFile(archive, 'w') as zip_file:
                zip_file.writestr('Microsoft.DotNet.Arcade.Sdk.nuspec', '<package><metadata><id>Microsoft.DotNet.Arcade.Sdk</id>'
                    '<version>1.0.0</version><authors>fixture</authors><description>fixture</description></metadata></package>')
                zip_file.writestr('sdk/Sdk.props', '<Project><PropertyGroup><DefineConstants>$(DefineConstants);DECLARED_PACKAGE_SDK</DefineConstants></PropertyGroup></Project>')
                zip_file.writestr('sdk/Sdk.targets', '<Project />')
            with zipfile.ZipFile(archive) as zip_file:
                zip_file.extractall(package)
            manifest = base / 'inputs.json'
            manifest.write_text(json.dumps({'inputs': [], 'packages': [{'id': 'Microsoft.DotNet.Arcade.Sdk',
                'version': '1.0.0', 'runfile': 'arcade'}], 'packageLock': '@sdk//:packages'}))
            flags = ['--package-build', '--resolve-references', '--inputs', str(manifest), '--runfiles', str(base / 'runfiles')]
            self.sync(flags=flags)
            expected = [(self.root / name).read_bytes() for name in ['graph.generated.json', 'graph.generated.bzl']]
            flags += ['--qualification-cache', str(base / 'cache')]
            self.assertIn('PROJECT_SYNC_RESTORE_CACHE miss', self.sync(flags=flags))
            output = self.sync(flags=flags)
            self.assertIn('PROJECT_SYNC_RESTORE_CACHE hit', output)
            self.assertIn('"compilations":0', output)
            self.assertEqual([(self.root / name).read_bytes() for name in ['graph.generated.json', 'graph.generated.bzl']], expected)

    @unittest.skipUnless(os.path.isfile("/usr/bin/bwrap"), "Linux qualification sandbox required")
    def test_qualification_cache_skips_both_overlapping_owners_and_consumers(self):
        for name in ['A', 'B', 'D']:
            directory = self.root / name
            directory.mkdir()
            (directory / (name + '.csproj')).write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                '<TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
            (directory / 'Code.cs').write_text('public class ' + name + ' {}')
        (self.root / 'App.csproj').write_text(self.project.replace('</Project>', '<ItemGroup>'
            '<Compile Remove="A/**;B/**;D/**" /><ProjectReference Include="B/B.csproj" /></ItemGroup></Project>'))
        target = ('<Project><Target Name="SharedProduct" AfterTargets="Build" Condition="&apos;$(MSBuildProjectName)&apos; == &apos;B&apos;">'
            '<MakeDir Directories="$(MSBuildThisFileDirectory)A/bin/Release/net10.0" />'
            '<WriteLinesToFile File="$(MSBuildThisFileDirectory)A/bin/Release/net10.0/shared.txt" Lines="shared" Overwrite="true" />'
            '</Target></Project>')
        (self.root / 'Directory.Build.targets').write_text(target)
        mapping = {'projectDefaults': {'referenceBoundary': True, 'documents': {'Directory.Build.targets': {
            'sha256': hashlib.sha256(target.encode()).hexdigest(), 'targets': ['SharedProduct'], 'tasks': [], 'inputs': []}}},
            'projects': {'B/B.csproj': {'outputFiles': ['A/bin/Release/net10.0/shared.txt']}}}
        with tempfile.TemporaryDirectory(prefix='qualification-overlap-') as directory:
            for warm in [False, True]:
                output = self.sync(mapping, flags=['A/A.csproj', 'D/D.csproj', '--package-build', '--resolve-references', '--qualification-cache', directory])
                report = next(json.loads(line.split(' ', 1)[1]) for line in output.splitlines() if line.startswith('PROJECT_SYNC_CACHE '))
                self.assertEqual(report, {'hits': int(warm), 'misses': int(not warm), 'uncacheable': 0, 'compilations': 3 if warm else 4})

    @unittest.skipUnless(os.path.isfile("/usr/bin/bwrap"), "Linux qualification sandbox required")
    def test_qualification_cache_rejects_source_and_sdk_aliases(self):
        with tempfile.TemporaryDirectory(prefix='qualification-alias-') as directory:
            link = Path(directory) / 'cache'
            for target in [self.root, SDK]:
                link.symlink_to(target, target_is_directory=True)
                try:
                    output = self.sync(flags=['--package-build', '--resolve-references', '--qualification-cache', str(link)], success=False)
                    self.assertIn('Qualification cache requires a separate directory on Linux', output)
                finally:
                    link.unlink()
            self.assertEqual({path.name for path in self.root.iterdir()}, {'App.csproj', 'Program.cs'})

    @unittest.skipUnless(os.path.isfile("/usr/bin/bwrap"), "Linux qualification sandbox required")
    def test_qualification_cache_rejects_output_directory_symlinks(self):
        (self.root / 'Directory.Build.targets').write_text('<Project><Target Name="LinkOutput" AfterTargets="Build">'
            '<Exec Command="ln -s /tmp &quot;$(OutputPath)escape&quot;" /></Target></Project>')
        with tempfile.TemporaryDirectory(prefix='qualification-links-') as directory:
            mapping = {'projectDefaults': {'referenceBoundary': True, 'documents': {'Directory.Build.targets': {
                'sha256': hashlib.sha256((self.root / 'Directory.Build.targets').read_bytes()).hexdigest(),
                'targets': ['LinkOutput'], 'tasks': [], 'inputs': []}}}}
            output = self.sync(mapping, flags=['--package-build', '--resolve-references', '--qualification-cache', directory], success=False)
            self.assertIn('Qualification output symlink', output)
            self.assertFalse(list(Path(directory).glob('*/manifest.json')))
            self.assertFalse((self.root / 'graph.generated.json').exists())

    def test_serial_and_parallel_qualification_preserve_selected_artifacts(self):
        references = []
        for name, properties in [('First', '<ProduceReferenceAssembly>false</ProduceReferenceAssembly>'),
                                 ('Second', '<GenerateDocumentationFile>true</GenerateDocumentationFile>')]:
            directory = self.root / name
            directory.mkdir()
            (directory / (name + '.csproj')).write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
                '<TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks>' + properties + '</PropertyGroup></Project>')
            (directory / 'Code.cs').write_text('/// <summary>Public dependency.</summary>\npublic class ' + name + ' {}')
            references.append('<ProjectReference Include="' + name + '/' + name + '.csproj" />')
        (self.root / 'App.csproj').write_text(self.project.replace('</Project>',
            '<ItemGroup><Compile Remove="First/**;Second/**" />' + ''.join(references) + '</ItemGroup></Project>'))
        expected = None
        for cpus in ['1', '4']:
            with patch.dict(os.environ, DOTNET_PROCESSOR_COUNT=cpus):
                self.sync(flags=['--package-build', '--resolve-references'])
            actual = [(self.root / name).read_bytes() for name in ['graph.generated.json', 'graph.generated.bzl']]
            if expected is not None:
                self.assertEqual(actual, expected)
            expected = actual
        selected = json.loads(actual[0])['Projects']['App.csproj']['Configurations'][0]
        self.assertEqual(selected['CompilerReferences'], {
            'First/First.csproj': 'First/bin/Release/net10.0/First.dll',
            'Second/Second.csproj': 'Second/obj/Release/net10.0/ref/Second.dll'})
        self.assertEqual(selected['DependencyCopies']['bin/Release/net10.0/Second.xml'],
            'Second/bin/Release/net10.0/Second.xml')
        self.assertFalse((self.root / 'bin').exists())
        self.assertFalse((self.root / 'First/obj').exists())
        if os.path.isfile('/usr/bin/bwrap'):
            with tempfile.TemporaryDirectory(prefix='qualification-multi-') as directory:
                for hits in [False, True]:
                    output = self.sync(flags=['--package-build', '--resolve-references', '--qualification-cache', directory])
                    report = next(json.loads(line.split(' ', 1)[1]) for line in output.splitlines() if line.startswith('PROJECT_SYNC_CACHE '))
                    self.assertEqual(report['compilations'] == 0, hits)
                    self.assertEqual([(self.root / name).read_bytes() for name in ['graph.generated.json', 'graph.generated.bzl']], expected)

    def test_multiple_roots_share_restore_walk_and_keep_root_hooks(self):
        for name in ['Library', 'Peer']:
            directory = self.root / name
            directory.mkdir()
            reference = '<ItemGroup><ProjectReference Include="../Library/Library.csproj" /></ItemGroup>' if name == 'Peer' else ''
            (directory / (name + '.csproj')).write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup>' + reference + '</Project>')
            (directory / 'Code.cs').write_text('public class ' + name + ' {}')
        (self.root / 'App.csproj').write_text(self.project.replace('</Project>',
            '<ItemGroup><Compile Remove="Library/**/*.cs;Peer/**/*.cs" /><ProjectReference Include="Library/Library.csproj" /></ItemGroup></Project>'))
        targets = ('<Project><Target Name="RestoreWalkProbe" BeforeTargets="_GenerateRestoreGraphProjectEntry">'
            '<Message Importance="high" Text="RESTORE_WALK: $(MSBuildProjectName)" /></Target>'
            '<Target Name="RestoreRootProbe" BeforeTargets="Restore">'
            '<Message Importance="high" Text="RESTORE_ROOT: $(MSBuildProjectName)" /></Target></Project>')
        (self.root / 'Directory.Build.targets').write_text(targets)
        mapping = {'projectDefaults': {'referenceBoundary': True, 'documents': {'Directory.Build.targets': {
            'sha256': hashlib.sha256(targets.encode()).hexdigest(),
            'targets': ['RestoreWalkProbe', 'RestoreRootProbe'], 'tasks': [], 'inputs': []}}}}
        flags = ['Peer/Peer.csproj', '--package-build', '--resolve-references']
        output = self.sync(mapping, flags=flags)
        self.assertEqual(output.count('RESTORE_WALK: Library'), 1, output)
        for name in ['App', 'Peer']:
            self.assertEqual(output.count('RESTORE_ROOT: ' + name), 1, output)
        contract = json.loads((self.root / 'graph.generated.json').read_text())
        for project in ['App.csproj', 'Peer/Peer.csproj']:
            self.assertEqual(contract['Projects'][project]['Configurations'][0]['CompilerReferences'],
                {'Library/Library.csproj': 'Library/obj/Release/net10.0/ref/Library.dll'})
        self.sync(mapping, flags=flags + ['--check'])
        self.assertFalse((self.root / 'obj').exists())
        self.assertFalse((self.root / 'Library/obj').exists())

    def test_multiple_restore_roots_keep_properties_and_fail_atomically(self):
        peer = self.root / 'Peer'
        peer.mkdir()
        (peer / 'Peer.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFrameworks>net10.0;net10.0-windows</TargetFrameworks></PropertyGroup></Project>')
        (peer / 'Code.cs').write_text('public class Peer {}')
        (self.root / 'App.csproj').write_text(self.project.replace('</Project>', '<ItemGroup><Compile Remove="Peer/**" /></ItemGroup></Project>'))
        (self.root / 'packages.lock.json').write_text('{"version":1,"dependencies":{"net10.0":{}}}')
        targets = ('<Project><Target Name="CheckRestoreProperties" BeforeTargets="Restore">'
            '<Error Condition="\'$(RoundTrip)\' != \'a;b,c%z\'" Text="Lost property escaping" />'
            '<Error Condition="\'$(MSBuildProjectName)\' == \'Peer\' and \'$(RootOnly)\' != \'peer\'" Text="Lost root override" />'
            '<Error Condition="\'$(MSBuildProjectName)\' == \'App\' and \'$(RootOnly)\' != \'app\'" Text="Leaked root override" />'
            '<Error Condition="\'$(MSBuildProjectName)\' == \'Peer\' and \'$(TargetFramework)\' != \'\'" Text="Restore lost authored frameworks" />'
            '<Error Condition="\'$(MSBuildProjectName)\' == \'App\' and \'$(RestoreLockedMode)\' != \'true\'" Text="Lost locked Restore" />'
            '<Error Condition="\'$(MSBuildProjectName)\' == \'Peer\' and \'$(RestoreLockedMode)\' == \'true\'" Text="Leaked locked Restore" />'
            '<Error Condition="\'$(FailRestore)\' == \'true\'" Text="Deliberate root failure" />'
            '</Target></Project>')
        (self.root / 'Directory.Build.targets').write_text(targets)
        mapping = {'projectDefaults': {'referenceBoundary': True, 'properties': {'RoundTrip': 'a;b,c%z', 'RootOnly': 'app'},
            'documents': {'Directory.Build.targets': {'sha256': hashlib.sha256(targets.encode()).hexdigest(),
                'targets': ['CheckRestoreProperties'], 'tasks': [], 'inputs': []}}},
            'entryProperties': {'Peer/Peer.csproj': {'RootOnly': 'peer'}}}
        flags = ['Peer/Peer.csproj', '--package-build', '--framework', 'net10.0', '--resolve-references']
        self.sync(mapping, flags=flags)
        generated = {name: (self.root / name).read_bytes() for name in ['graph.generated.json', 'graph.generated.bzl']}
        self.sync(mapping, flags=flags + ['--check'])
        mapping['entryProperties']['Peer/Peer.csproj']['FailRestore'] = 'true'
        self.assertIn('Deliberate root failure', self.sync(mapping, flags=flags, success=False))
        for name, contents in generated.items():
            self.assertEqual((self.root / name).read_bytes(), contents)
        self.assertFalse((peer / 'obj').exists())

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
