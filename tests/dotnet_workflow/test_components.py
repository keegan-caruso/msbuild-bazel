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
    @unittest.skipUnless(sys.platform=='linux', 'Linux discovery sandbox control')
    def test_linux_discovery_denies_undeclared_reads_writes_and_network(self):
        hidden=self.root/'hidden';hidden.write_text('must not be visible')
        value=self.invoke('linux-sandbox-control',dict(sdk=str(self.dotnet.parent),folder=str(self.root/'declared'),output=str(self.root/'scratch'),hidden=str(hidden)))
        self.assertEqual(value,dict(hidden=True,read=True,deniedWrite=True,deniedNetwork=True))
        self.assertEqual(hidden.read_text(),'must not be visible')

    def test_controller_session_rejects_other_repository_and_sdk(self):
        command=[str(self.dotnet),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),'workflow-session']
        for repository,sdk,error in [(str(self.root),str(self.dotnet.parent),'repository differs'),(str(ROOT),str(self.root/'sdk'),'SDK differs')]:
            result=subprocess.run(command,input=json.dumps(dict(schemaVersion=1,repository=repository,sdkRoot=sdk))+'\n',capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn(error,json.loads(result.stdout)['error'])

    def test_controller_session_rejects_changed_loaded_files(self):
        folder=self.root/'controller'
        shutil.copytree(ROOT/'tools/Preparation/bin/Release/net10.0',folder)
        guard=folder/'session-input';guard.write_text('before')
        process=subprocess.Popen([str(self.dotnet),str(folder/'Preparation.dll'),'workflow-session'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            process.stdin.write('{}\n');process.stdin.flush()
            self.assertIn('Invalid workflow request',json.loads(process.stdout.readline())['error'])
            info=guard.stat();guard.write_text('after!');os.utime(guard,ns=(info.st_atime_ns,info.st_mtime_ns))
            process.stdin.write('{}\n');process.stdin.flush()
            self.assertIn('Leased inputs changed',json.loads(process.stdout.readline())['error'])
        finally:
            process.stdin.close();process.wait(timeout=10);process.stdout.close();process.stderr.close()

    def test_protected_store_mutable_fallback(self):
        root=self.root/'ordinary';root.mkdir();(root/'file').write_text('content')
        value=self.invoke('protected-store',dict(root=str(root),mutable=str(self.root/'mutable')))
        self.assertFalse(value['eligible']);self.assertEqual(value['hits'],0);self.assertEqual(value['roots'],0)
        self.assertEqual(value['restartHits'],0)

    @unittest.skipUnless(sys.platform=='darwin', 'Protected system Nix store is macOS-only')
    def test_protected_store_real_root_and_restart(self):
        sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
        if not str(sdk).startswith('/nix/store/'):self.skipTest('Requires system Nix SDK')
        value=self.invoke('protected-store',dict(root=str(sdk.parents[1]),mutable=str(self.root/'mutable')))
        self.assertTrue(value['eligible']);self.assertEqual(value['hits'],2);self.assertEqual(value['roots'],1)
        self.assertEqual(value['fullScans'],3);self.assertEqual(value['restartHits'],0)

    def test_action_cache_defers_and_orders_publication(self):
        import base64
        data=b'cache payload';blob=sha(data);action='a'*64
        put=lambda path,body:dict(method='PUT',path=path,body=base64.b64encode(body).decode())
        with CacheServer(0) as server:
            request=dict(endpoint=server.url+'/bazel',directory=str(self.root/'pending'),upload=True,publish=True,
                         requests=[put('ac/'+action,b'action metadata'),put('cas/'+blob,data)],
                         probeBeforePublish=['ac/'+action,'cas/'+blob])
            value=self.invoke('action-cache-gate',request)
            self.assertEqual(value['upstreamBefore'],[404,404])
            self.assertEqual(value['beforePublish']['publishedObjects'],0)
            self.assertEqual(value['afterPublish']['publishedObjects'],2)
            self.assertEqual([e['path'] for e in server.events if e['method']=='PUT'],['/bazel/cas/'+blob,'/bazel/ac/'+action])
            self.assertEqual(server.data['/bazel/cas/'+blob],data)
    def test_action_cache_discard_readonly_and_bad_digest(self):
        import base64
        data=b'value';blob=sha(data)
        for upload,path,expected in [(True,'cas/'+blob,200),(False,'cas/'+blob,403),(True,'cas/'+'0'*64,400),(True,'ac/not-a-digest',400)]:
            with self.subTest(upload=upload,path=path), CacheServer(0) as server:
                value=self.invoke('action-cache-gate',dict(endpoint=server.url+'/bazel',directory=str(self.root/str(expected)),upload=upload,publish=False,
                    requests=[dict(method='PUT',path=path,body=base64.b64encode(data).decode())],probeBeforePublish=[]))
                self.assertEqual(value['responses'][0]['status'],expected)
                self.assertEqual(value['afterPublish']['publishedObjects'],0)
                self.assertFalse(server.data)
    def test_action_cache_never_publishes_ac_after_upload_failure(self):
        import base64
        data=b'value';blob=sha(data);action='a'*64
        for corrupt in (False,True):
            with self.subTest(corrupt=corrupt), CacheServer(0) as server:
                if not corrupt:server.offline_prefixes=['/bazel/cas/']
                body=b'corrupt' if corrupt else data
                self.invoke('action-cache-gate',dict(endpoint=server.url+'/bazel',directory=str(self.root/str(corrupt)),upload=True,publish=True,
                    requests=[dict(method='PUT',path='ac/'+action,body=base64.b64encode(b'metadata').decode()),
                              dict(method='PUT',path='cas/'+blob,body=base64.b64encode(body).decode())],probeBeforePublish=[]),False)
                self.assertFalse(server.data)
                self.assertFalse(any(e['method']=='PUT' and '/ac/' in e['path'] for e in server.events))
    def test_action_cache_reads_and_endpoint_validation(self):
        import base64
        data=b'value';blob=sha(data)
        with CacheServer(0) as server:
            server.data['/bazel/cas/'+blob]=data
            value=self.invoke('action-cache-gate',dict(endpoint=server.url+'/bazel',directory=str(self.root/'read'),upload=False,publish=False,
                requests=[dict(method='GET',path='cas/'+blob),dict(method='HEAD',path='cas/'+blob),dict(method='GET',path='ac/'+'0'*64)],probeBeforePublish=[]))
            self.assertEqual([r['status'] for r in value['responses']],[200,200,404])
            self.assertEqual(base64.b64decode(value['responses'][0]['body']),data)
        for endpoint in ('file:///tmp/cache','grpc://localhost:9092','https://user:pass@example.test','https://example.test/?token=secret','https://example.test/#fragment'):
            self.invoke('action-cache-endpoint',dict(endpoint=endpoint),False)
        self.assertEqual(self.invoke('action-cache-endpoint',dict(endpoint='https://example.test/cache/')),'https://example.test/cache')
    def test_verification_shares_reads_but_checks_each_expectation_and_pass(self):
        source=self.root/'source';source.mkdir();value=source/'value'
        value.write_text('value')
        request=dict(path=str(source))
        self.assertEqual(self.invoke('verification',request),dict(requests=2,scans=1))
        self.assertEqual(self.invoke('verification',dict(request,linkedPolicy=True)),dict(requests=3,scans=2))
        for flag in ('mutate','differentExpectation','laterMutation'):
            value.write_text('value')
            self.assertIn('Leased inputs changed',self.invoke('verification',dict(request,**{flag:True}),False))
    def test_alias_hash_reuse_preserves_records_and_rechecks_later_scans(self):
        root=self.root/'tree';root.mkdir();(root/'value').write_text('value')
        (root/'alias-a').symlink_to('value');(root/'alias-b').symlink_to('value')
        value=self.invoke('alias-snapshot',dict(path=str(root)))
        self.assertEqual(value['files'],3)
        self.assertEqual(value['contentBytes'],15)
        self.assertEqual(value['reusedFiles'],2)
        self.assertEqual(value['reusedBytes'],10)
        self.assertIn('Leased inputs changed',self.invoke('alias-snapshot',dict(path=str(root),mutate=True),False))

    def test_stream_hash_matches_sha256_across_buffer_boundaries(self):
        path=self.root/'value'
        for size in (0,1,65535,65536,65537,17*1024*1024+3):
            data=(bytes(range(251))*(size//251+1))[:size];path.write_bytes(data)
            self.assertEqual(self.invoke('hash-regular',dict(path=str(path))),dict(size=size,sha256=sha(data)))
    def test_stream_hash_rejects_symlinks_and_special_files(self):
        path=self.root/'value';path.write_bytes(b'value')
        link=self.root/'link';link.symlink_to(path)
        self.assertIn('Cannot open regular input',self.invoke('hash-regular',dict(path=str(link)),False))
        fifo=self.root/'fifo';os.mkfifo(fifo)
        self.assertIn('regular file',self.invoke('hash-regular',dict(path=str(fifo)),False))
        self.assertIn('regular file',self.invoke('hash-regular',dict(path=str(self.root)),False))
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
    def test_orchard_profile_requires_exact_anchors_and_import_hashes(self):
        repository=self.root/'repository';(repository/'tools').mkdir(parents=True)
        workspace=self.root/'workspace';workspace.mkdir();anchor=workspace/'global.json';anchor.write_text('anchor')
        sdk=self.root/'sdk';sdk.mkdir()
        policy=dict(schemaVersion=1,anchors={'global.json':sha(b'anchor')},packages=['example/1.0'],imports={'workspace/App.csproj':sha(b'project'),'dotnet/sdk/target':sha(b'sdk'),'packages/example/1.0/build/t':sha(b'target')})
        (repository/'tools/orchard-discovery-policy.json').write_text(json.dumps(policy))
        def check(path,content):return self.invoke('orchard-profile',dict(repository=str(repository),workspace=str(workspace),sdk=str(sdk),path=str(path),sha256=sha(content)))
        self.assertTrue(check(workspace/'App.csproj',b'project')['accepted'])
        self.assertTrue(check(sdk/'sdk/target',b'sdk')['accepted'])
        self.assertTrue(check(workspace/'.nuget/packages/example/1.0/build/t',b'target')['accepted'])
        self.assertFalse(check(workspace/'App.csproj',b'changed')['accepted'])
        self.assertFalse(check(workspace/'Other.csproj',b'project')['accepted'])
        anchor.write_text('changed')
        self.assertEqual(check(workspace/'App.csproj',b'project'),dict(accepted=False,packages=[]))

    def test_native_analyzers_preserve_executable_dependency_closure(self):
        import copy
        prepared,graph=self.native_fixture()
        app=graph['nodes'][0]
        for name,framework,deps in [('Generator','netstandard2.0',['helper']),('Helper','netstandard2.0',[])]:
            node=copy.deepcopy(app);node.update(id=name.lower(),project=f'workspace/{name}/{name}.csproj',targetFramework=framework,dependencies=deps)
            node['globalProperties']={'configuration':'Release'}
            node['execution']={'outputDirectory':f'workspace/{name}/bin/Release/{framework}','referenceDirectory':f'workspace/{name}/obj/Release/{framework}/ref'}
            node['outputs']=[{'kind':'assembly','path':f'workspace/{name}/bin/Release/{framework}/{name}.dll'}]
            node['inputs']=[];graph['nodes'].append(node)
            (prepared/'restore'/f'{name.lower()}.json').write_text('{}')
            (prepared/'package-manifests'/f'{name.lower()}.json').write_text('{"packages":[]}')
        app['dependencies']=['generator'];app['execution']['analyzerReferences']=['workspace/Generator/Generator.csproj']
        output=self.root/'mixed'
        self.invoke('native-plan',dict(prepared=str(prepared),graph=graph,output=str(output),toolchain='a'*64))
        projects=json.loads((output/'manifest.json').read_text())['projects']
        self.assertEqual(projects['App/App.csproj']['analyzers'],['Generator/Generator.csproj'])
        self.assertNotIn('implementation',projects['App/App.csproj'])
        for name in ('Generator','Helper'):
            self.assertTrue(projects[f'{name}/{name}.csproj']['implementation'])
            self.assertEqual(projects[f'{name}/{name}.csproj']['targetFramework'],'netstandard2.0')
        app['execution']['analyzerReferences']=['workspace/Helper/Helper.csproj']
        self.assertIn('Analyzer reference is not a graph dependency',self.invoke('native-plan',dict(prepared=str(prepared),graph=graph,output=str(self.root/'bad'),toolchain='a'*64),False))

    def test_indexed_binding_matches_legacy_and_checks_roles_and_identity(self):
        prepared,graph=self.native_fixture();discovery=self.root/'discovery'
        self.invoke('native-plan',dict(prepared=str(prepared),graph=graph,output=str(discovery),toolchain='a'*64,includePayload=False))
        source=prepared/'src/App/App.cs';source.write_text('class A { public int Value => 7; }')
        request=dict(discovery=str(discovery),project='App/App.csproj',dependencies=[],sources=[dict(source=str(source),destination='App/App.cs')])
        self.invoke('bind-sources',dict(request,output=str(self.root/'indexed')))
        index=discovery/'binding-index.json';saved=index.read_text();index.unlink()
        self.invoke('bind-sources',dict(request,output=str(self.root/'legacy')))
        for p in (self.root/'indexed').iterdir():self.assertEqual(json.loads(p.read_text()),json.loads((self.root/'legacy'/p.name).read_text()))
        index.write_text(saved);value=json.loads(saved);value['protectedSources']=['App/App.cs'];index.write_text(json.dumps(value))
        self.assertIn('compile-only input',self.invoke('bind-sources',dict(request,output=str(self.root/'role')),False))
        index.write_text(saved);record=discovery/value['projects']['App/App.csproj']['record'];record.write_text('{}')
        self.assertIn('Corrupt discovery identity',self.invoke('bind-sources',dict(request,output=str(self.root/'identity')),False))

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

    def worker_identity(self):
        return dict(policy='darwin-arm64-worker-v1',scope='independent-qualified-workers',controllerSdkClosure='a'*64,
                    execution=dict(os='macOS',osBuild='build',architecture='Arm64',cpuModel='model',cpuCount=10),
                    systemTools={'bazel':'b'*64},environmentPolicy='fixed',hostPolicy='reviewed')

    def test_worker_identity_accepts_equal_records_and_rejects_each_changed_role(self):
        worker=self.worker_identity()
        linux=json.loads(json.dumps(worker));linux["policy"]="linux-arm64-worker-v1"
        self.assertIn("Incompatible worker",self.invoke("worker-compatible",dict(producer=worker,consumer=linux),False))
        self.assertTrue(self.invoke('worker-compatible',dict(producer=worker,consumer=worker)))
        for field in worker:
            with self.subTest(field=field):
                changed=json.loads(json.dumps(worker))
                changed[field]='c'*64 if field=='controllerSdkClosure' else 'different'
                self.invoke('worker-compatible',dict(producer=changed,consumer=worker),False)
        self.invoke('worker-compatible',dict(producer=None,consumer=worker),False)

    def test_incompatible_snapshot_stops_before_artifact_download(self):
        worker=self.worker_identity();producer=json.loads(json.dumps(worker));producer['execution']['osBuild']='other'
        snapshot=dict(policy='dotnet-native-snapshot-v1',worker=producer,preparation='d'*64,projects=[])
        blob=json.dumps(snapshot).encode();key=sha(blob)
        with CacheServer() as server:
            server.data['/native/cas/'+key]=blob
            error=self.invoke('worker-snapshot',dict(endpoint=server.url+'/native',digest=key,worker=worker),False)
            self.assertIn('Incompatible worker',error)
            self.assertEqual(len(server.events),1)

    def test_remote_meter_matches_actual_requests_and_payload_bytes(self):
        with CacheServer() as server:
            data=b'downloaded';key=sha(data);server.data['/native/cas/'+key]=data
            value=self.invoke('remote-meter',dict(endpoint=server.url+'/native',digest=key,data='uploaded'))
            self.assertEqual(value['getRequests'],1);self.assertEqual(value['headRequests'],2);self.assertEqual(value['putRequests'],1)
            self.assertEqual(value['downloadBytes'],len(data));self.assertEqual(value['uploadBytes'],len(b'uploaded'))
            self.assertEqual(len(server.events),4);self.assertEqual(value['failures'],0)
