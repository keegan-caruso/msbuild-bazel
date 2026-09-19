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
            graph = dict(entryPoints=['B'],nodes=[node('A',[]),node('B',['A']),node('Unrelated',[])], graphInputs=[dict(kind='import',path='workspace/Shared.targets')])
            for item in graph['nodes']:
                name=item['id']
                item['inputs'] += [dict(kind='resource',path=f'workspace/{name}/View.cshtml'),dict(kind='import',path=f'workspace/{name}/Build.targets'),dict(kind='restore',path=f'workspace/{name}/obj/project.assets.json')]
            graph['nodes'][0]['inputs'].append(dict(kind='package',path='workspace/.nuget/packages/package-a/1.0.0/lib/a.dll'))
            graph['nodes'][1]['inputs'].append(dict(kind='package',path='packages/package-b/2.0.0/lib/b.dll'))
            graph['nodes'][2]['inputs'].append(dict(kind='package',path='packages/unrelated/3.0.0/lib/c.dll'))
            graph['nodes'][1]['inputs'].append(dict(kind='content',path='workspace/Linked/site.css'))
            (discovery/'graph.json').write_text(json.dumps(graph))
            layout = root/'layout.json'
            def run(command, request):
                path=root/'request.json';path.write_text(json.dumps(request))
                return subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),command,'--request',str(path)],capture_output=True,text=True,timeout=30)
            result=run('owned-export-layout',dict(graph=str(discovery/'graph.json'),output=str(layout)))
            self.assertEqual(result.returncode,0,result.stderr)
            expected=json.loads(layout.read_text());self.assertNotIn(str(root),layout.read_text())
            self.assertEqual(expected['projects']['A/A.csproj']['structural'], ['A/Build.targets','A/View.cshtml','Shared.targets'])
            self.assertEqual(expected['projects']['B/B.csproj']['structural'], ['A/Build.targets','A/View.cshtml','B/Build.targets','B/View.cshtml','Linked/site.css','Shared.targets'])
            self.assertEqual(expected['projects']['A/A.csproj']['packages'], ['package-a/1.0.0'])
            self.assertEqual(expected['projects']['B/B.csproj']['packages'], ['package-a/1.0.0','package-b/2.0.0'])
            graph['nodes'][0]['inputs'][0]['sha256']='after';(discovery/'graph.json').write_text(json.dumps(graph))
            for case in ['valid','legacy','edge','source','structural-missing','structural-extra','structural-escape','package-missing','package-extra','package-escape','configuration','extra-project']:
                value=copy.deepcopy(expected)
                if case=='legacy':
                    for project in value['projects'].values(): project.pop('structural');project.pop('packages')
                if case=='structural-missing':value['projects']['B/B.csproj']['structural'].remove('Linked/site.css')
                if case=='structural-extra':value['projects']['B/B.csproj']['structural'].append('Unrelated/View.cshtml')
                if case=='structural-escape':value['projects']['B/B.csproj']['structural'].append('../escape')
                if case=='package-missing':value['projects']['B/B.csproj']['packages'].remove('package-a/1.0.0')
                if case=='package-extra':value['projects']['B/B.csproj']['packages'].append('unrelated/3.0.0')
                if case=='package-escape':value['projects']['B/B.csproj']['packages'].append('../escape')
                if case=='edge':value['projects']['B/B.csproj']['dependencies']=[]
                if case=='source':value['projects']['B/B.csproj']['sources'].append('B/Added.cs')
                if case=='configuration':value['configuration']='Debug'
                if case=='extra-project':value['projects']['C/C.csproj']=dict(dependencies=[],sources=[])
                layout.write_text(json.dumps(value));output=root/(case+'.json')
                result=run('owned-validate-layout',dict(discovery=str(discovery),layout=str(layout),output=str(output)))
                self.assertEqual(result.returncode==0,case in ['valid','legacy'],result.stderr)
                self.assertEqual(output.exists(),case in ['valid','legacy'])
