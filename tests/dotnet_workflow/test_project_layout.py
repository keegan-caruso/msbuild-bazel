"""Portable project layouts must be checked against authoritative discovery."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ProjectLayout(unittest.TestCase):
    def test_portable_layout_rejects_stale_edges_membership_and_configuration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); discovery = root/'discovery'; discovery.mkdir()
            def node(name, dependencies):
                return dict(id=name, project=f'workspace/{name}/{name}.csproj', globalProperties=dict(configuration='Release', targetframework='net10.0'), targetFramework='net10.0', outputType='Library', execution=dict(outputDirectory=f'workspace/{name}/bin/Release/net10.0', referenceDirectory=f'workspace/{name}/obj/Release/net10.0/ref'), outputs=[dict(kind='assembly',path=f'workspace/{name}/bin/Release/net10.0/{name}.dll')], dependencies=dependencies, inputs=[dict(kind='source',path=f'workspace/{name}/Value.cs',sha256='before')])
            graph = dict(entryPoints=['B'],nodes=[node('A',[]),node('B',['A'])])
            (discovery/'graph.json').write_text(json.dumps(graph))
            layout = root/'layout.json'
            def run(command, request):
                path=root/'request.json';path.write_text(json.dumps(request))
                return subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),command,'--request',str(path)],capture_output=True,text=True,timeout=30)
            result=run('owned-export-layout',dict(graph=str(discovery/'graph.json'),output=str(layout)))
            self.assertEqual(result.returncode,0,result.stderr)
            expected=json.loads(layout.read_text());self.assertNotIn(str(root),layout.read_text())
            graph['nodes'][0]['inputs'][0]['sha256']='after';(discovery/'graph.json').write_text(json.dumps(graph))
            for case in ['valid','edge','source','configuration','extra-project']:
                value=copy.deepcopy(expected)
                if case=='edge':value['projects']['B/B.csproj']['dependencies']=[]
                if case=='source':value['projects']['B/B.csproj']['sources'].append('B/Added.cs')
                if case=='configuration':value['configuration']='Debug'
                if case=='extra-project':value['projects']['C/C.csproj']=dict(dependencies=[],sources=[])
                layout.write_text(json.dumps(value));output=root/(case+'.json')
                result=run('owned-validate-layout',dict(discovery=str(discovery),layout=str(layout),output=str(output)))
                self.assertEqual(result.returncode==0,case=='valid',result.stderr)
                self.assertEqual(output.exists(),case=='valid')
