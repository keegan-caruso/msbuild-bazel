import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from probe_http_cache import CacheServer
from native_graph import materialize


def sha(data):return hashlib.sha256(data).hexdigest()
def digest(value):return sha(json.dumps(value,sort_keys=True,separators=(',',':')).encode())


class Components(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dotnet=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'
        result=subprocess.run([str(cls.dotnet),'build',str(ROOT/'tests/Preparation.Tests'),'-c','Release','--nologo'],capture_output=True,text=True)
        if result.returncode:raise RuntimeError(result.stdout+result.stderr)
        cls.runner=ROOT/'tests/Preparation.Tests/bin/Release/net10.0/Preparation.Tests.dll'
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=str(Path(tempfile.gettempdir()).resolve()));self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
    def invoke(self,component,request,success=True):
        path=self.root/'request.json';path.write_text(json.dumps(request))
        result=subprocess.run([str(self.dotnet),str(self.runner),component,str(path)],capture_output=True,text=True,timeout=30)
        if success:self.assertEqual(result.returncode,0,result.stderr)
        else:self.assertNotEqual(result.returncode,0);return result.stderr
        return json.loads(result.stdout) if result.stdout.strip() else None
    def test_snapshot_copy_modes_and_readonly_cleanup(self):
        source=self.root/'source';source.mkdir();(source/'value').write_bytes(b'value');(source/'empty').mkdir();(source/'empty').chmod(0o555)
        snapshot=self.invoke('snapshot',dict(path=str(source)))
        self.assertEqual(snapshot['value']['sha256'],sha(b'value'))
        output=self.root/'copy'
        self.assertEqual(self.invoke('copy',dict(source=str(source),output=str(output))),snapshot)
        self.invoke('remove',dict(path=str(output)));self.assertFalse(output.exists())
        (source/'empty').chmod(0o755)
    def test_snapshot_rejects_links(self):
        source=self.root/'source';source.mkdir();(source/'link').symlink_to('/etc/hosts')
        self.assertIn('Linked',self.invoke('snapshot',dict(path=str(source)),False))
    def test_snapshot_rejects_fifo_without_blocking(self):
        source=self.root/'source';source.mkdir();os.mkfifo(source/'fifo')
        self.assertIn('regular',self.invoke('snapshot',dict(path=str(source)),False))
    def nuget_fixture(self):
        source=self.root/'source';(source/'App/obj').mkdir(parents=True)
        cache=self.root/'cache';(cache/'example/1.0').mkdir(parents=True);(cache/'example/1.0/value').write_bytes(b'package')
        assets=dict(packageFolders={str(cache):{}},libraries={'example/1.0':dict(type='package',path='example/1.0')},project=str(source))
        (source/'App/obj/project.assets.json').write_text(json.dumps(assets))
        return source,cache
    def test_nuget_stages_selected_closure_without_mutating_global(self):
        source,cache=self.nuget_fixture();output=self.root/'output'
        result=self.invoke('nuget',dict(source=str(source),output=str(output),cache=str(cache)))
        self.assertEqual(result['packages'],1);self.assertEqual((output/'.nuget/packages/example/1.0/value').read_bytes(),b'package')
        (cache/'example/1.0/value').write_bytes(b'changed');self.assertEqual((output/'.nuget/packages/example/1.0/value').read_bytes(),b'package')
        assets=json.loads((output/'App/obj/project.assets.json').read_text());self.assertEqual(assets['project'],str(output));self.assertIn(str(output/'.nuget/packages'),assets['packageFolders'])
    def test_missing_package_rejects(self):
        source,cache=self.nuget_fixture();shutil.rmtree(cache/'example')
        self.assertIn('run restore',self.invoke('nuget',dict(source=str(source),output=str(self.root/'output'),cache=str(cache)),False))
    def test_linked_destination_is_not_deleted(self):
        source,cache=self.nuget_fixture();target=self.root/'target';target.mkdir();(target/'sentinel').write_text('keep');output=self.root/'output';output.symlink_to(target,target_is_directory=True)
        self.invoke('nuget',dict(source=str(source),output=str(output),cache=str(cache)),False);self.assertEqual((target/'sentinel').read_text(),'keep')
    def native_fixture(self):
        prepared=self.root/'prepared';(prepared/'src/App').mkdir(parents=True);(prepared/'restore').mkdir();(prepared/'package-manifests').mkdir()
        (prepared/'src/App/App.csproj').write_text('<Project/>');(prepared/'src/App/App.cs').write_text('class A {}')
        (prepared/'restore/app.json').write_text(json.dumps({'App/obj/project.assets.json':'{}','App/obj/project.nuget.cache':'{}'}))
        (prepared/'package-manifests/app.json').write_text(json.dumps(dict(packages=[])))
        inputs=[dict(path='workspace/App/'+name,kind=kind,sha256=sha((prepared/'src/App'/name).read_bytes())) for name,kind in [('App.csproj','project'),('App.cs','source')]]
        graph=dict(nodes=[dict(id='app',project='workspace/App/App.csproj',globalProperties=dict(configuration='Release',targetframework='net10.0'),targetFramework='net10.0',outputType='Library',execution=dict(outputDirectory='workspace/App/bin/Release/net10.0',referenceDirectory='workspace/App/obj/Release/net10.0/ref'),outputs=[dict(kind='assembly',path='workspace/App/bin/Release/net10.0/App.dll')],dependencies=[],inputs=inputs)],entryPoints=['app'],graphInputs=[])
        return prepared,graph
    def test_native_materialization_matches_python_oracle(self):
        prepared,graph=self.native_fixture();expected=self.root/'python';actual=self.root/'dotnet'
        materialize(prepared,graph,expected,'a'*64)
        self.invoke('native-plan',dict(prepared=str(prepared),graph=graph,output=str(actual),toolchain='a'*64))
        for name in ('manifest.json','restore.json','entry.json','graph.json','identity-records.json'):
            self.assertEqual(json.loads((actual/name).read_text()),json.loads((expected/name).read_text()),name)
    def refresh_fixture(self):
        prepared,graph=self.native_fixture();output=self.root/'plan';workspace=prepared/'src'
        self.invoke('native-plan',dict(prepared=str(prepared),graph=graph,output=str(output),toolchain='a'*64))
        before=self.invoke('snapshot',dict(path=str(workspace)))
        return output,workspace,before
    def test_existing_body_edit_refreshes_one_identity(self):
        plan,workspace,before=self.refresh_fixture();prior=json.loads((plan/'manifest.json').read_text())
        (workspace/'App/App.cs').write_text('class A { int M()=>1; }');after=self.invoke('snapshot',dict(path=str(workspace)))
        value=self.invoke('refresh',dict(plan=str(plan),workspace=str(workspace),before=before,after=after));self.assertIsNotNone(value)
        self.assertNotEqual(prior,json.loads((plan/'manifest.json').read_text()))
        self.assertEqual((plan/'src/App/App.cs').read_bytes(),(workspace/'App/App.cs').read_bytes())
    def test_new_source_and_project_edit_require_discovery(self):
        for kind in ('new','project'):
            with self.subTest(kind=kind):
                prepared,graph=self.native_fixture() if not (self.root/'prepared').exists() else (self.root/'prepared',json.loads((self.root/'plan/graph.json').read_text()))
                if not (self.root/'plan').exists():self.invoke('native-plan',dict(prepared=str(prepared),graph=graph,output=str(self.root/'plan'),toolchain='a'*64))
                workspace=prepared/'src';before=self.invoke('snapshot',dict(path=str(workspace)))
                path=workspace/'App'/('New.cs' if kind=='new' else 'App.csproj');path.write_text('changed')
                after=self.invoke('snapshot',dict(path=str(workspace)))
                self.assertIsNone(self.invoke('refresh',dict(plan=str(self.root/'plan'),workspace=str(workspace),before=before,after=after)))
    def test_remote_archive_paths_and_hashes_reject(self):
        with CacheServer() as server:
            for case in ('escape','digest'):
                with self.subTest(case=case):
                    data=io.BytesIO()
                    with zipfile.ZipFile(data,'w') as z:z.writestr('../escape' if case=='escape' else 'preparation.json','{}')
                    blob=data.getvalue();key=sha(blob);server.data['/native/cas/'+key]=blob if case=='escape' else b'corrupt'
                    self.invoke('remote-preparation',dict(endpoint=server.url+'/native',digest=key,output=str(self.root/case)),False)
                    self.assertFalse((self.root/'escape').exists())

    def test_parallel_publication_has_stable_snapshot_identity(self):
        cache=self.root/'cache';cache.mkdir()
        for i in range(20):
            key=sha(str(i).encode());folder=cache/key;folder.mkdir()
            payload=b'compiled fixture'
            result=dict(key=key,inputs='a'*64,toolchain='b'*64,project=f'Project{i}/App.csproj')
            result_bytes=json.dumps(result).encode()
            artifacts=json.dumps([dict(path='app/App.dll',size=len(payload),sha256=sha(payload))]).encode()
            seal=json.dumps(dict(schemaVersion=1,resultsSha256=sha(result_bytes),artifactsSha256=sha(artifacts))).encode()
            files={'bundle.json':seal,'results.json':result_bytes,'artifacts.json':artifacts,'artifacts/app/App.dll':payload}
            for name,data in files.items():
                path=folder/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        with CacheServer() as server:
            request=dict(endpoint=server.url+'/native',cache=str(cache))
            first=self.invoke('publish',request)
            before=len(server.events)
            for _ in range(4):self.assertEqual(self.invoke('publish',request),first)
            self.assertFalse(any(e['method']=='PUT' for e in server.events[before:]))

    def test_source_and_controller_must_be_disjoint(self):
        source=self.root/'source';source.mkdir()
        request=dict(schemaVersion=1,repository=str(source),workspace=str(source),
                     state=str(self.root/'state'),output=str(self.root/'report'),
                     entry='App.csproj',operation='build')
        self.assertIn('disjoint',self.invoke('workflow',request,False))
        self.assertFalse((self.root/'state').exists())
