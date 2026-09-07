"""S01/S03/S04: actual analysis and prepared-workspace contracts, on pinned Bazel."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'tests/graph'))
from prepare_graph import prepare, write_build, DOTNET_ROOT
from test_export_graph import write_fixture
from starlark import call

BAZEL = Path(os.environ.get('SPIKE_BAZEL', ROOT / '.tools/bin/bazel'))


class CoreValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = Path(tempfile.mkdtemp(prefix='starlark-core-')).resolve()
        print('Starlark evidence: ' + str(cls.evidence), file=sys.stderr)
        cls.work = cls.evidence / 'preparation'
        write_fixture(cls.work)
        # Supported filename characters must survive source copying, Starlark
        # parsing, labels and action input discovery, including quotes and spaces.
        (cls.work / 'src/Shared/space "quoted" file.cs').write_text('// declared input\n')
        cls.env = dict(os.environ, NUGET_PACKAGES=str(cls.work / '.nuget/packages'),
                       DOTNET_CLI_HOME=str(cls.evidence / 'home'), DOTNET_NOLOGO='1',
                       DOTNET_CLI_TELEMETRY_OPTOUT='1')
        cls.command('exporter', [DOTNET_ROOT / 'dotnet', 'build', ROOT / 'tools/GraphExport', '-c', 'Release'], ROOT)
        cls.command('restore', [DOTNET_ROOT / 'dotnet', 'msbuild', 'build.proj', '-t:Restore', '-p:Configuration=Release'], cls.work)
        cls.manifest = cls.evidence / 'graph.json'
        request = cls.evidence / 'request.json'
        request.write_text(json.dumps(dict(schemaVersion=1, workspace=str(cls.work),
            dotnetRoot=str(DOTNET_ROOT), sdkVersion='10.0.100', packageRoot=cls.env['NUGET_PACKAGES'],
            entryPoints=[dict(project='build.proj', globalProperties={'Configuration': 'Release'})], output=str(cls.manifest))))
        cls.command('export', [DOTNET_ROOT / 'dotnet', ROOT / 'tools/GraphExport/bin/Release/net10.0/GraphExport.dll', '--request', request], cls.work)
        cls.generated = cls.evidence / 'generated'
        cls.graph = prepare(cls.work, cls.manifest, cls.generated, environment=cls.env)

    @classmethod
    def command(cls, name, args, cwd):
        result = subprocess.run(list(map(str, args)), cwd=cwd, env=cls.env, text=True,
                                capture_output=True, timeout=600)
        (cls.evidence / (name + '.log')).write_text(result.stdout + result.stderr)
        if result.returncode:
            raise AssertionError(name + ': ' + result.stdout + result.stderr)
        return result.stdout

    def bazel(self, name, args, workspace=None):
        workspace = workspace or ROOT
        key = 'generated' if workspace == self.generated else 'analysis'
        return self.command(name, [BAZEL, '--batch', '--nohome_rc', '--noworkspace_rc',
            '--output_user_root=' + str(self.evidence / 'user'),
            '--output_base=' + str(self.evidence / ('base-' + key)), *args,
            '--noshow_progress', '--color=no', '--curses=no'], workspace)

    def check_format(self, workspace):
        self.command('format-' + workspace.name, [sys.executable, ROOT / 'scripts/check-starlark.py', '--workspace', workspace], ROOT)

    def test_analysis_contracts(self):
        self.bazel('analysis-tests', ['test', '//tests/starlark:core', '--test_output=errors', '--nocache_test_results'])

    def test_execution_policy_is_declared(self):
        subjects = 'set(' + ' '.join('//tests/starlark:' + name for name in ('shared', 'left', 'right', 'app', 'explicit_shared', 'explicit_app')) + ')'
        data = json.loads(self.bazel('analysis-actions', ['aquery', 'mnemonic(MsbuildProject, ' + subjects + ')', '--output=jsonproto']))
        actions = data['actions']
        self.assertEqual(len(actions), 6)
        for action in actions:
            self.assertEqual({p['key']: p['value'] for p in action['executionInfo']}, {'block-network': '1', 'no-remote': '1'})

    def test_generated_actions_and_direct_edges(self):
        self.check_format(self.generated)
        graph = self.graph
        names = {n['id']: Path(n['project']).stem for n in graph['nodes']}
        ids = {v: k for k, v in names.items()}
        expected = {'Shared': [], 'Left': ['Shared'], 'Right': ['Shared'], 'App': ['Left', 'Right']}
        # cquery reports configured direct rule dependencies; filter the SDK and
        # source files without replacing direct graph edges by replay closure.
        for name, deps in expected.items():
            label = '//:node_' + ids[name]
            lines = self.bazel('edges-' + name, ['cquery', 'deps(' + label + ', 1)', '--output=label'], self.generated).splitlines()
            actual = {names[line.split('node_', 1)[1].split()[0]] for line in lines if line.startswith('//:node_')}
            self.assertEqual(actual, {name, *deps})
        data = json.loads(self.bazel('generated-actions', ['aquery', 'mnemonic(MsbuildProject, deps(//:all))', '--output=jsonproto'], self.generated))
        self.assertEqual(len(data['actions']), 4)
        targets = {t['id']: t['label'].split('node_')[-1] for t in data['targets']}
        fragments = {p['id']: p for p in data['pathFragments']}
        def path(identity):
            part = fragments[identity]
            return (path(part['parentId']) + '/' if part.get('parentId') else '') + part['label']
        artifacts = {a['id']: path(a['pathFragmentId']) for a in data['artifacts']}
        sets = {s['id']: s for s in data['depSetOfFiles']}
        def inputs(identity):
            group = sets[identity]
            result = {artifacts[a] for a in group.get('directArtifactIds', [])}
            for child in group.get('transitiveDepSetIds', []): result.update(inputs(child))
            return result
        for action in data['actions']:
            name = names[targets[action['targetId']]]
            declared = set().union(*(inputs(s) for s in action['inputDepSetIds']))
            bundles = {names[Path(p).name.removeprefix('node_').removesuffix('.bundle')] for p in declared if p.endswith('.bundle')}
            self.assertEqual(bundles, set(expected[name]) | ({'Shared'} if name == 'App' else set()))
            self.assertFalse(any(p.endswith('.diagnostics') for p in declared))
            compile_inputs = [p for p in declared if p.endswith('.cs')]
            self.assertTrue(compile_inputs)
            self.assertTrue(all('/' + name + '/' in p for p in compile_inputs), compile_inputs)
            if name == 'Shared': self.assertTrue(any('space "quoted" file.cs' in p for p in declared))
            self.assertEqual({p['key']: p['value'] for p in action['executionInfo']}, {'block-network': '1', 'no-remote': '1'})

    def test_equivalent_manifest_order_emits_identical_build(self):
        # Exercise the production materializer after validation, without weakening
        # prepare()'s discovery freshness check to accept an altered manifest.
        original = (self.generated / 'BUILD.bazel').read_bytes()
        reordered = copy.deepcopy(self.graph)
        reordered['nodes'].reverse()
        reordered['entryPoints'].reverse()
        for node in reordered['nodes']:
            node['dependencies'].reverse()
            node['inputs'].reverse()
        write_build(self.work, reordered, self.generated)
        self.assertEqual((self.generated / 'BUILD.bazel').read_bytes(), original)

    def test_source_archive_checker_preserves_exclusions(self):
        archive = self.evidence / 'source-archive'
        (archive / 'scripts').mkdir(parents=True)
        (archive / '.tools/bin').mkdir(parents=True)
        for name in ('check-starlark.py', 'starlark-tools.json'):
            shutil.copyfile(ROOT / 'scripts' / name, archive / 'scripts' / name)
        shutil.copy2(ROOT / '.tools/bin/buildifier', archive / '.tools/bin/buildifier')
        (archive / 'BUILD.bazel').write_text('filegroup(name = "source")\n')
        (archive / 'nested').mkdir()
        (archive / 'nested/defs.bzl').write_text('"""Owned declarations."""\n')
        for directory in ('.tools', '.cache', 'artifacts', 'nested/bin', 'nested/obj', 'bazel-out'):
            path = archive / directory
            path.mkdir(parents=True, exist_ok=True)
            (path / 'invalid.bzl').write_text('this is deliberately invalid starlark !')
        (archive / 'linked').symlink_to(archive / 'artifacts', target_is_directory=True)
        command = [sys.executable, archive / 'scripts/check-starlark.py']
        text = self.command('source-archive-check', command, archive)
        self.assertIn('2 files', text)
        (archive / 'nested/defs.bzl').write_text('this is deliberately invalid starlark !')
        result = subprocess.run(list(map(str, command)), cwd=archive, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)

    def test_unsupported_label_paths_fail_before_publication(self):
        for index, character in enumerate((':', '\\', '\n', '\r')):
            with self.subTest(character=character):
                graph = copy.deepcopy(self.graph)
                graph['nodes'][0]['project'] = 'workspace/invalid' + character + 'project.csproj'
                manifest = self.evidence / f'invalid-{index}.json'
                manifest.write_text(json.dumps(graph))
                output = self.evidence / f'invalid-{index}'
                with self.assertRaisesRegex(ValueError, 'unsupported Bazel workspace path'):
                    prepare(self.work, manifest, output, environment=self.env)
                self.assertFalse(output.exists())

    def test_format_gate_rejects_without_rewriting(self):
        work = self.evidence / 'invalid-format'
        work.mkdir()
        file = work / 'BUILD.bazel'
        for source in ('filegroup(name="bad")\n',
                       'load(":unused.bzl", "unused")\n\nfilegroup(name = "bad")\n'):
            file.write_text(source)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/check-starlark.py'),
                                     '--workspace', str(work)], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(file.read_text(), source)

    def test_serializer_escaping_and_typed_values_load(self):
        work = self.evidence / 'escaping'
        work.mkdir()
        (work / 'MODULE.bazel').write_text('module(name = "escaping")\n')
        (work / 'BUILD.bazel').write_text(call('filegroup', name='escaped', srcs=[], testonly=True,
            tags=['quote " newline\n slash\\ tab\t', 'unicode café']).lstrip())
        self.check_format(work)
        self.bazel('escaping', ['query', '//:escaped'], work)


if __name__ == '__main__':
    unittest.main()
