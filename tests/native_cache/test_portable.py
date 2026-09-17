import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from portable_cache import capture, environment, tool_identity, unpack, seed, publish, sha, reset_workspace
from synthetic_graph import generate
from probe_http_cache import CacheServer

class Portable(unittest.TestCase):
    def test_environment_is_explicit(self):
        env=environment(Path('/sdk'),Path('/home-role'),Path('/temp-role'),Path('/workspace-role'))
        self.assertNotIn('MSBuildSDKsPath',env)
        self.assertEqual(env['HOME'],'/home-role')
        self.assertEqual(env['PATH'],'/usr/bin:/bin')

    def test_tool_installation_path_is_not_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);paths=[]
            for name in ('one','two'):
                p=root/name/'runner.dll';p.parent.mkdir();p.write_bytes(b'original');paths.append(p)
            self.assertEqual(tool_identity('sdk',[paths[0]],[],[]),tool_identity('sdk',[paths[1]],[],[]))
            paths[1].write_bytes(b'changed')
            self.assertNotEqual(tool_identity('sdk',[paths[0]],[],[]),tool_identity('sdk',[paths[1]],[],[]))

    def test_independent_restore_and_exact_authored_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            roots=[Path(temp)/'one',Path(temp)/'two'];snapshots=[]
            for root in roots:
                generate(root,2,'fan');home=root.parent/(root.name+'-home')
                for project in root.rglob('*.csproj'):
                    obj=project.parent/'obj';obj.mkdir()
                    (obj/'project.assets.json').write_text(json.dumps(dict(libraries={},projectFilePath=str(project),config=str(home/'config'))))
                    for ext in ('props','targets'):(obj/(project.name+'.nuget.g.'+ext)).write_text('<Project/>')
                    (obj/'project.nuget.cache').write_text(json.dumps(dict(dgSpecHash=root.name)))
                snapshots.append(capture(root,home,Path('/sdk')))
            self.assertEqual(snapshots[0][2],snapshots[1][2])
            for root in roots:(root/'N0000/Value.cs').write_text('const string path="'+str(root)+'";')
            a=capture(roots[0],roots[0].parent/'one-home',Path('/sdk'))
            b=capture(roots[1],roots[1].parent/'two-home',Path('/sdk'))
            self.assertNotEqual(a[2],b[2])
            (roots[0]/'N0000/obj/project.assets.json').unlink()
            with self.assertRaisesRegex(ValueError,'incomplete'):capture(roots[0],roots[0].parent/'one-home',Path('/sdk'))

    def test_verified_download_skips_only_identical_publication(self):
        with tempfile.TemporaryDirectory() as temp, CacheServer(0) as server:
            root=Path(temp);folder=root/'output';bundle=folder/('a'*64)
            (bundle/'artifacts').mkdir(parents=True)
            def write(payload):
                (bundle/'artifacts/out.dll').write_bytes(payload)
                result=json.dumps(dict(key='a'*64,project='p.csproj',inputs='inputs',toolchain='sdk')).encode()
                artifacts=json.dumps([dict(path='out.dll',size=len(payload),sha256=sha(payload))]).encode()
                (bundle/'results.json').write_bytes(result);(bundle/'artifacts.json').write_bytes(artifacts)
                (bundle/'bundle.json').write_text(json.dumps(dict(schemaVersion=1,resultsSha256=sha(result),artifactsSha256=sha(artifacts))))
            endpoint=server.url+'/native';manifest=dict(toolchain='sdk',projects={'p.csproj':dict(identity='inputs')})
            write(b'one');catalog=publish(endpoint,folder)['entries']
            receipt=seed(endpoint,catalog,manifest,root/'seeds')
            before=len(server.events)
            self.assertEqual(publish(endpoint,folder,verified_blobs=receipt['verifiedBlobs'])['entries'],catalog)
            self.assertEqual(len(server.events),before)
            write(b'two')
            changed=publish(endpoint,folder,verified_blobs=receipt['verifiedBlobs'])
            self.assertNotEqual(changed['entries'][0]['blob'],catalog[0]['blob'])
            self.assertEqual(server.events[-1]['method'],'PUT')
            # A failed download provides no receipt: rebuilding must repair remote bytes.
            write(b'one');server.data['/native/cas/'+catalog[0]['blob']]=b'corrupt'
            rejected=seed(endpoint,catalog,manifest,root/'bad-seeds')
            self.assertEqual(rejected['verifiedBlobs'],[])
            self.assertEqual(len(rejected['rejected']),1)
            publish(endpoint,folder,verified_blobs=rejected['verifiedBlobs'])
            repaired=seed(endpoint,catalog,manifest,root/'repaired')
            self.assertEqual(repaired['accepted'],['a'*64])

    def test_workspace_lock_survives_only_identical_module(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'generated';module='module(name="owned")\n'
            reset_workspace(root,module)
            lock=root/'MODULE.bazel.lock';lock.write_bytes(b'owned lock bytes')
            (root/'old-source').write_text('stale')
            reset_workspace(root,module)
            self.assertEqual(lock.read_bytes(),b'owned lock bytes')
            self.assertFalse((root/'old-source').exists())
            reset_workspace(root,module+'bazel_dep(name="platforms", version="0.0.11")\n')
            self.assertFalse(lock.exists())
            lock.write_bytes(b'new lock')
            reset_workspace(root,(root/'MODULE.bazel').read_text(),preserve_lock=False)
            self.assertFalse(lock.exists())

    def test_malformed_remote_metadata_is_a_cache_miss(self):
        with tempfile.TemporaryDirectory() as temp, CacheServer(0) as server:
            for index,parts in enumerate((dict(seal=[],results={},artifacts=[]),
                                         dict(seal={},results=[],artifacts=[]),
                                         dict(seal={},results={},artifacts=[None]))):
                result=json.dumps(parts['results']).encode();artifacts=json.dumps(parts['artifacts']).encode()
                seal=parts['seal']
                if isinstance(seal,dict):seal.update(schemaVersion=1,resultsSha256=sha(result),artifactsSha256=sha(artifacts))
                payload=io.BytesIO()
                with zipfile.ZipFile(payload,'w') as z:
                    z.writestr('bundle.json',json.dumps(seal));z.writestr('results.json',result);z.writestr('artifacts.json',artifacts)
                blob=sha(payload.getvalue());server.data['/native/cas/'+blob]=payload.getvalue()
                record=dict(key='a'*64,project='p.csproj',inputs='inputs',toolchain='sdk',blob=blob)
                receipt=seed(server.url+'/native',[record],dict(toolchain='sdk',projects={'p.csproj':dict(identity='inputs')}),Path(temp)/str(index))
                self.assertEqual(receipt['accepted'],[])
                self.assertEqual(len(receipt['rejected']),1)

    def test_archive_escape_rejected(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as z:z.writestr('../escape',b'invalid')
        with self.assertRaisesRegex(ValueError,'archive'):unpack(data.getvalue())

if __name__=='__main__':unittest.main()
