"""Project artifact boundaries preserve legacy binding and reject stale declarations."""
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


class ProjectTemplates(unittest.TestCase):
    def invoke(self, command, request, accepted=True):
        path = self.root/'request.json'; path.write_text(json.dumps(request))
        result = subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'),
            str(ROOT/'tests/Preparation.Tests/bin/Release/net10.0/Preparation.Tests.dll'), command, str(path)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode == 0, accepted, result.stderr)
        return result.stderr

    def fixture(self, global_source=False):
        self.discovery = self.root/'discovery'; self.discovery.mkdir(); (self.discovery/'project-records').mkdir()
        empty = hashlib.sha256(b'').hexdigest()
        self.sources = {'A.csproj': ['A.cs', 'Shared.cs'], 'B.csproj': ['B.cs', 'Shared.cs'], 'C.csproj': ['C.cs']}
        graph_inputs = [dict(path='workspace/Shared.cs', kind='source', sha256=empty)] if global_source else []
        self.records = {project: dict(inputs={'workspace/'+name: empty for name in names}, graphInputs=graph_inputs,
            packages=dict(packages=[]), restore={project+'/project.assets.json': project}) for project, names in self.sources.items()}
        self.records['A.csproj']['inputs']['workspace/A.txt'] = empty
        self.manifest = dict(policy='fixture', toolchain='fixture', projects={project: dict(identity=digest(record),
            dependencies=['A.csproj'] if project=='B.csproj' else []) for project, record in self.records.items()})
        self.payload = {name: empty for names in self.sources.values() for name in names}; self.payload['A.txt'] = empty
        self.index = dict(policy='project-bindings-v1', graphInputs=graph_inputs, protectedSources=[], projects={project:
            dict(record='project-records/'+project+'.json', sources=names) for project, names in self.sources.items()})
        self.write_fixture()
        for names in self.sources.values():
            for name in names: (self.root/name).write_text('changed '+name)

    def write_fixture(self):
        for name, value in {'manifest.json': self.manifest, 'identity-records.json': self.records,
            'payload.json': self.payload, 'binding-index.json': self.index}.items():
            (self.discovery/name).write_text(json.dumps(value))
        for project, record in self.records.items():
            (self.discovery/'project-records'/f'{project}.json').write_text(json.dumps(record))

    def templates(self, name):
        outputs = {project: str(self.root/name/project) for project in self.records}
        self.invoke('project-templates', dict(discovery=str(self.discovery), outputs=outputs))
        return outputs

    def bind_request(self, discovery, project, output):
        return dict(discovery=str(discovery), project=project, output=str(output),
            dependencies=self.manifest['projects'][project]['dependencies'],
            sources=[dict(source=str(self.root/name), destination=name) for name in self.sources[project]])

    def tree(self, path):
        return {p.name: p.read_bytes() for p in Path(path).iterdir() if p.is_file()}

    def test_templates_match_legacy_for_linked_and_global_sources(self):
        for global_source in (False, True):
            with self.subTest(global_source=global_source), tempfile.TemporaryDirectory() as directory:
                self.root=Path(directory); self.fixture(global_source); outputs=self.templates('templates')
                for project in self.records:
                    legacy=self.root/'legacy'/project; scoped=self.root/'scoped'/project
                    self.invoke('bind-sources', self.bind_request(self.discovery, project, legacy))
                    self.invoke('bind-sources', self.bind_request(outputs[project], project, scoped))
                    self.assertEqual(self.tree(legacy), self.tree(scoped))

    def test_unrelated_template_stays_identical_after_resource_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            self.root=Path(directory); self.fixture(); before=self.templates('before')
            changed=hashlib.sha256(b'changed resource').hexdigest()
            self.records['A.csproj']['inputs']['workspace/A.txt']=changed; self.payload['A.txt']=changed
            self.manifest['projects']['A.csproj']['identity']=digest(self.records['A.csproj']); self.write_fixture()
            after=self.templates('after')
            self.assertEqual(self.tree(before['C.csproj']), self.tree(after['C.csproj']))
            for project in ['A.csproj', 'B.csproj']: self.assertNotEqual(self.tree(before[project]), self.tree(after[project]))

    def test_rejects_stale_layout_sources_edges_and_corrupt_record(self):
        with tempfile.TemporaryDirectory() as directory:
            self.root=Path(directory); self.fixture(); outputs=self.templates('templates')
            self.assertIn('differs from discovery', self.invoke('project-templates', dict(discovery=str(self.discovery), outputs={}), False))
            request=self.bind_request(outputs['B.csproj'], 'B.csproj', self.root/'out')
            for field in ['dependencies', 'sources']:
                self.assertIn('differs from discovery', self.invoke('bind-sources', dict(request, **{field: []}), False))
            path=Path(outputs['B.csproj'])/'binding.json'; binding=json.loads(path.read_text())
            binding['records']['A.csproj']['inputs']['workspace/Shared.cs']='0'*64; path.write_text(json.dumps(binding))
            self.assertIn('Corrupt discovery identity', self.invoke('bind-sources', request, False))
