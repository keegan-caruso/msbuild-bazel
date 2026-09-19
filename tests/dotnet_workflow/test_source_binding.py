"""Source binding must preserve immutable discovery inputs and actual content identity."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


class SourceBinding(unittest.TestCase):
    def test_bazel_symlinks_readonly_templates_and_source_identity(self):
        for metadata_only in [False, True]:
            with self.subTest(metadata_only=metadata_only), tempfile.TemporaryDirectory() as folder:
                root = Path(folder); template = root/'template'; template.mkdir()
                empty = hashlib.sha256(b'').hexdigest()
                record = dict(inputs={'workspace/A.cs': empty}, graphInputs=[])
                documents = {
                    'graph.json': dict(nodes=[dict(inputs=[dict(kind='source', path='workspace/A.cs', sha256=empty)])], graphInputs=[]),
                    'identity-records.json': {'App.csproj': record},
                    'manifest.json': dict(projects={'App.csproj': dict(identity=digest(record))}),
                }
                if metadata_only: documents['payload.json'] = {'A.cs': empty}
                for name, value in documents.items(): (template/name).write_text(json.dumps(value))
                if not metadata_only:
                    (template/'src').mkdir(); (template/'src/A.cs').write_bytes(b'')
                sandbox = root/'sandbox'; sandbox.mkdir()
                originals = {}
                for path in template.rglob('*'):
                    if not path.is_file(): continue
                    originals[path] = path.read_bytes(); path.chmod(0o444)
                    target = sandbox/path.relative_to(template); target.parent.mkdir(parents=True, exist_ok=True); target.symlink_to(path)
                source = root/'actual.cs'; source.write_bytes(b'public class A { public int Value => 7; }\n')
                link = root/'source.cs'; link.symlink_to(source)
                output = root/'output'
                request = root/'request.json'; request.write_text(json.dumps(dict(discovery=str(sandbox), output=str(output), sources=[dict(source=str(link), destination='A.cs')])))
                command = [str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'), str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'), 'owned-bind-sources', '--request', str(request)]
                p = subprocess.run(command, capture_output=True, text=True, timeout=30)
                self.assertEqual(p.returncode, 0, p.stderr)
                expected = hashlib.sha256(source.read_bytes()).hexdigest()
                actual_record = json.loads((output/'identity-records.json').read_text())['App.csproj']
                self.assertEqual(actual_record['inputs']['workspace/A.cs'], expected)
                self.assertEqual(json.loads((output/'manifest.json').read_text())['projects']['App.csproj']['identity'], digest(actual_record))
                self.assertEqual(json.loads((output/'graph.json').read_text())['nodes'][0]['inputs'][0]['sha256'], expected)
                if metadata_only:
                    self.assertFalse((output/'src').exists())
                    self.assertEqual(json.loads((output/'payload.json').read_text())['A.cs'], expected)
                else: self.assertEqual((output/'src/A.cs').read_bytes(), source.read_bytes())
                for path, content in originals.items(): self.assertEqual(path.read_bytes(), content)

    def test_native_rejects_mismatched_direct_payload_before_msbuild(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); plan = root/'plan'; plan.mkdir()
            (plan/'payload.json').write_text(json.dumps({'A.cs': hashlib.sha256(b'expected').hexdigest()}))
            source = root/'A.cs'; source.write_bytes(b'changed')
            request = root/'request.json'
            request.write_text(json.dumps(dict(entry='App.csproj', output=str(root/'output'), diagnostics=str(root/'diagnostics'), manifest=str(plan/'manifest.json'), restore=str(plan/'restore.json'), sources=[dict(source=str(source), destination='A.cs')], seeds=[], preparedPlan=str(plan))))
            command = [str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'), str(ROOT/'tools/NativeProjectCache/bin/Release/net10.0/NativeProjectCache.dll'), '--portable-request', str(request)]
            p = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('Prepared payload differs from declared input', p.stderr)
            self.assertFalse((root/'diagnostics/action.json').exists())

    def test_project_binding_rejects_stale_edges_and_source_membership(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); template = root/'template'; template.mkdir()
            empty = hashlib.sha256(b'').hexdigest()
            records = {name: dict(inputs={'workspace/'+source: empty}, graphInputs=[], packages={'packages':[]}, restore={name+'/project.assets.json': name}) for name, source in [('A.csproj', 'A.cs'), ('B.csproj', 'B.cs')]}
            documents = {
                'graph.json': dict(nodes=[dict(project='workspace/'+name, inputs=[dict(kind='source', path='workspace/'+name.replace('.csproj', '.cs'), sha256=empty)]) for name in records], graphInputs=[]),
                'manifest.json': dict(projects={name: dict(identity=digest(record), dependencies=[] if name=='A.csproj' else ['A.csproj']) for name, record in records.items()}),
                'identity-records.json': records,
                'payload.json': {'A.cs': empty, 'B.cs': empty},
            }
            for name, value in documents.items(): (template/name).write_text(json.dumps(value))
            source = root/'B.cs'; source.write_text('class B {}')
            for label, dependencies, sources, accepted in [
                ('valid', ['A.csproj'], [dict(source=str(source), destination='B.cs')], True),
                ('stale-edge', [], [dict(source=str(source), destination='B.cs')], False),
                ('stale-source', ['A.csproj'], [], False),
            ]:
                with self.subTest(label=label):
                    output = root/label; request = root/'request.json'
                    request.write_text(json.dumps(dict(discovery=str(template), output=str(output), project='B.csproj', dependencies=dependencies, sources=sources)))
                    p = subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'), str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'), 'owned-bind-sources', '--request', str(request)], capture_output=True, text=True, timeout=30)
                    self.assertEqual(p.returncode==0, accepted, p.stderr)
                    if accepted:
                        self.assertEqual(set(json.loads((output/'payload.json').read_text())), {'B.cs'})
                        self.assertEqual(set(json.loads((output/'manifest.json').read_text())['projects']), {'A.csproj', 'B.csproj'})
                        self.assertEqual(json.loads((output/'restore.json').read_text()), {'B.csproj/project.assets.json': 'B.csproj'})
                        self.assertEqual({p.name for p in output.iterdir()}, {'payload.json', 'manifest.json', 'entry.json', 'restore.json'})
                        for name, value in documents.items(): self.assertEqual(json.loads((template/name).read_text()), value)
                    else: self.assertIn('differs from discovery', p.stderr)

    def test_composer_rejects_escaping_cache_key_before_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); bundle = root/'input/cache/entry'; bundle.mkdir(parents=True)
            (bundle/'results.json').write_text(json.dumps(dict(project='App.csproj', key='../escape', targets={}, inputs='fixture', toolchain='fixture')))
            request = root/'request.json'; request.write_text(json.dumps(dict(entry='App.csproj', output=str(root/'output'), bundles=[str(root/'input')])))
            p = subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'), str(ROOT/'tools/NativeProjectCache/bin/Release/net10.0/NativeProjectCache.dll'), '--compose-projects', str(request)], capture_output=True, text=True, timeout=30)
            self.assertNotEqual(p.returncode, 0)
            self.assertIn('Invalid project bundle identity', p.stderr)
            self.assertFalse((root/'output').exists())

    def test_composer_refreshes_entry_once_and_validates_every_producer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            def bundle(name, files):
                parent = root/name; path = parent/'cache'/('a'*64); path.mkdir(parents=True)
                items = []
                for relative, content in files.items():
                    target = path/'artifacts'/relative; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(content)
                    items.append(dict(path=relative, size=len(content), sha256=hashlib.sha256(content).hexdigest()))
                (path/'artifacts.json').write_text(json.dumps(items))
                (path/'results.json').write_text(json.dumps(dict(project=name+'/'+name+'.csproj', key=hashlib.sha256(name.encode()).hexdigest(), targets={}, inputs='fixture', toolchain='fixture')))
                (path/'bundle.json').write_text(json.dumps(dict(schemaVersion=1, resultsSha256=hashlib.sha256((path/'results.json').read_bytes()).hexdigest(), artifactsSha256=hashlib.sha256((path/'artifacts.json').read_bytes()).hexdigest())))
                return parent, path
            dep, dep_bundle = bundle('Dep', {'Dep/bin/Release/net10.0/Dep.dll': b'current'})
            app, app_bundle = bundle('App', {'App/bin/Release/net10.0/App.dll': b'app', 'App/bin/Release/net10.0/Dep.dll': b'historical'})
            unused, unused_bundle = bundle('Unused', {'Unused/bin/Release/net10.0/Unused.dll': b'unused'})
            original = {path: path.read_bytes() for parent in [dep, app, unused] for path in parent.rglob('*') if path.is_file()}
            for corrupt in [False, True]:
                if corrupt: (unused_bundle/'artifacts/Unused/bin/Release/net10.0/Unused.dll').write_bytes(b'corrupt')
                output = root/('corrupt' if corrupt else 'output'); request = root/'request.json'
                request.write_text(json.dumps(dict(entry='App/App.csproj', output=str(output), bundles=[str(dep), str(app), str(unused)])))
                p = subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'), str(ROOT/'tools/NativeProjectCache/bin/Release/net10.0/NativeProjectCache.dll'), '--compose-projects', str(request)], capture_output=True, text=True, timeout=30)
                if corrupt:
                    self.assertNotEqual(p.returncode, 0)
                    self.assertIn('dependency artifact corrupt', p.stderr)
                    self.assertFalse(output.exists())
                else:
                    self.assertEqual(p.returncode, 0, p.stderr)
                    self.assertEqual((output/'app/Dep.dll').read_bytes(), b'current')
                    self.assertEqual(len(list((output/'cache').iterdir())), 1)
                    self.assertEqual(len(list((output/'runtime').iterdir())), 1)
                    self.assertFalse((output/'app/Unused.dll').exists())
                    for path, content in original.items(): self.assertEqual(path.read_bytes(), content)
