"""Differential tests for the production .NET fresh-preparation boundary."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT / '.tools/dotnet')).resolve()
DLL = ROOT / 'tools/Preparation/bin/Release/net10.0/Preparation.dll'
BRIDGE = ROOT / 'tests/Preparation.Tests/bin/Release/net10.0/Preparation.Tests.dll'
sys.path.insert(0, str(ROOT / 'tools'))
import graph_packages
import preparation_identity


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rejections = load('preparation_rejection_control', 'tests/graph_execution/test_prepare_graph.py')
frameworks = load('framework_control', 'tests/graph_execution/test_framework_selection.py')
analyzers = load('analyzer_control', 'tests/graph_packages/test_analyzer_packages.py')


def invoke(command, request, bridge=False):
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / 'request.json'
        path.write_text(json.dumps(request))
        args = [str(SDK / 'dotnet'), str(BRIDGE if bridge else DLL), command]
        if not bridge:
            args.append('--request')
        result = subprocess.run([*args, str(path)], text=True, capture_output=True)
        if result.returncode:
            raise ValueError(result.stderr)
        return result.stdout


def prepare(workspace, manifest, output, **options):
    request = dict(schemaVersion=1, repository=str(ROOT), workspace=str(workspace),
                   manifest=str(manifest), output=str(output), sdkRoot=str(SDK))
    names = {'sdk_version': 'sdkVersion', 'sdk_root': 'sdkRoot'}
    request.update({names[k]: str(v) for k, v in options.items()})
    invoke('prepare', request)


class Rejections(rejections.PreparationRejection):
    def setUp(self):
        super().setUp()
        self.control = patch.object(rejections, 'prepare', prepare)
        self.control.start()
        self.addCleanup(self.control.stop)

    def test_leased_preparation_rejects_unqualified_toolchain_overrides(self):
        # Leased preparation is deliberately outside this migration step.
        with self.assertRaisesRegex(ValueError, 'unsupported preparation request'):
            invoke('prepare', dict(schemaVersion=1, leased=True))


class Frameworks(frameworks.FrameworkSelection):
    def setUp(self):
        self.control = patch.object(frameworks, 'framework_selections', lambda nodes, closure:
                                    json.loads(invoke('frameworks', nodes, bridge=True)))
        self.control.start()
        self.addCleanup(self.control.stop)


class Components(unittest.TestCase):
    def test_canonical_json_matches_python(self):
        for value in ({'b': '\U0001f600<>+\"\n', 'a': {'z': [True, False, None, 42]}}, {'unicode': 'é\u2028\u007f'}, {'\ue000': 'bmp', '\U00010000': 'astral'}, {}):
            self.assertEqual(invoke('digest', value).strip(), preparation_identity.digest(value))

    def test_thousand_node_chain(self):
        graph = {str(i): {'dependencies': [str(i+1)] if i < 999 else []} for i in range(1000)}
        actual = json.loads(invoke('closures', graph, bridge=True))
        for i in range(1000):
            self.assertEqual(set(actual[str(i)]), {str(n) for n in range(i, 1000)})

    def test_package_payloads_match_and_mutations_reject(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            payload, archive = analyzers.AnalyzerPackageIntegrity().make_package(root)
            expected_manifest, expected_paths = graph_packages.stage(root, 'App/App.csproj', root/'python', 'app')
            request = dict(repository=str(ROOT), workspace=str(root), output=str(root/'dotnet'))
            actual = json.loads(invoke('package', request, bridge=True))
            self.assertEqual(actual, dict(manifest=expected_manifest, paths=expected_paths))
            self.assertEqual(json.loads((root/'python'/expected_manifest).read_text()), json.loads((root/'dotnet'/expected_manifest).read_text()))
            for path in expected_paths:
                self.assertEqual((root/'python'/path).read_bytes(), (root/'dotnet'/path).read_bytes())
            with self.assertRaisesRegex(ValueError, 'package changed'):
                invoke('package', dict(request, mutate=str(payload)), bridge=True)
            with self.assertRaisesRegex(ValueError, 'hash-mismatch: package payload'):
                invoke('package', request, bridge=True)
            payload.unlink()
            with self.assertRaisesRegex(ValueError, 'missing-input'):
                invoke('package', request, bridge=True)
            archive.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, 'archive disagrees'):
                invoke('package', request, bridge=True)

    def test_compile_boundary_rejects_implementation_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root/'App/obj').mkdir(parents=True)
            (root/'App/obj/project.assets.json').write_text(json.dumps(dict(libraries={}, targets={'net10.0': {}}, project={'frameworks': {'net10.0': {}}})))
            node = dict(id='one', dependencies=[], project='workspace/App/App.csproj',
                        targetFramework='net10.0', outputType='Library',
                        globalProperties={'configuration': 'Release'},
                        inputs=[dict(kind='project', path='workspace/App/App.csproj')])
            request = dict(repository=str(ROOT), workspace=str(root), output=str(root/'unused'), graph={'nodes': [node]})
            for body in ('<Target Name="Build"/>', '<UsingTask TaskName="T" AssemblyFile="X.dll"/>',
                         '<ItemGroup><ProjectReference Include="Gen.csproj" OutputItemType="Analyzer"/></ItemGroup>',
                         '<ItemGroup><Reference Include="X"/></ItemGroup>',
                         '<ItemGroup><Content Include="data"/></ItemGroup>',
                         '<PropertyGroup><Version>$([System.DateTime]::Now)</Version></PropertyGroup>'):
                (root/'App/App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk">'+body+'</Project>')
                with self.subTest(body=body), self.assertRaises(ValueError):
                    invoke('compile', request, bridge=True)

    def test_output_collision_does_not_replace_existing_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, 'Output already exists'):
                prepare(root/'absent', root/'missing.json', root)
            self.assertTrue(root.is_dir())


if __name__ == '__main__':
    unittest.main()
