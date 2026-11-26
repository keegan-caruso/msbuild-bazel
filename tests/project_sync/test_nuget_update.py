"""Native NuGet acquisition reuse must preserve ordinary update/check products."""
import base64
from collections import Counter
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
DOTNET = SDK / ("dotnet.exe" if os.name == "nt" else "dotnet")
RUNNER = ROOT / 'tools/ProjectSync/bin/Release/net11.0/ProjectSync.dll'


class NuGetUpdateCacheTests(unittest.TestCase):
    def test_fsharp_projects_in_shared_directory_get_distinct_native_locks(self):
        with tempfile.TemporaryDirectory(prefix='nuget-fsharp-locks-') as temporary:
            root = Path(temporary)
            (root / 'Directory.Build.props').write_text('<Project><PropertyGroup><BaseIntermediateOutputPath>obj/$(MSBuildProjectName)/</BaseIntermediateOutputPath></PropertyGroup></Project>')
            (root / 'NuGet.Config').write_text('<configuration><packageSources><clear/></packageSources></configuration>')
            project = """<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>
<TargetFramework>net11.0</TargetFramework><DisableImplicitFSharpCoreReference>true</DisableImplicitFSharpCoreReference>
</PropertyGroup>{}</Project>"""
            (root / 'Library.fsproj').write_text(project.format(''))
            (root / 'App.fsproj').write_text(project.format('<ItemGroup><ProjectReference Include="Library.fsproj" /></ItemGroup>'))
            result = subprocess.run([str(DOTNET), str(RUNNER), 'nuget-update', str(root), str(SDK),
                                     'App.fsproj', '--distdir', str(root / 'distdir')], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((root / 'packages.App.lock.json').is_file())
            self.assertTrue((root / 'packages.Library.lock.json').is_file())
            self.assertFalse((root / 'packages.lock.json').exists())

    def test_restore_disables_ambient_msbuild_server(self):
        with tempfile.TemporaryDirectory(prefix='nuget-server-control-') as temporary:
            root = Path(temporary)
            (root / 'NuGet.Config').write_text('<configuration><packageSources><clear/></packageSources></configuration>')
            (root / 'App.csproj').write_text("""<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>""" + RUNNER.parent.name + """</TargetFramework></PropertyGroup>
<Target Name="CheckServerIsolation" BeforeTargets="Restore"><Error Condition="'$(MSBUILDUSESERVER)' != '0'" Text="Restore must not use an ambient MSBuild server" /></Target></Project>""")
            result = subprocess.run([str(DOTNET), str(RUNNER), 'nuget-update', str(root), str(SDK),
                                     'App.csproj', '--distdir', str(root / 'distdir')], text=True, capture_output=True,
                                    env=dict(os.environ, DOTNET_CLI_USE_MSBUILD_SERVER='true', MSBUILDUSESERVER='1'))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_explicit_http_cache_reuses_download_without_changing_locks(self):
        self.check_http_cache(False)

    def test_default_http_cache_reuses_download_without_changing_locks(self):
        self.check_http_cache(True)

    def test_no_http_cache_keeps_acquisition_disposable(self):
        self.check_http_cache(None)

    def check_http_cache(self, automatic):
        package = io.BytesIO()
        with zipfile.ZipFile(package, 'w') as archive:
            archive.writestr('Fixture.Cache.nuspec', '<package><metadata><id>Fixture.Cache</id><version>1.0.0</version><authors>fixture</authors><description>cache control</description></metadata></package>')
            archive.writestr('buildTransitive/Fixture.Cache.props', '<Project/>')
        data = package.getvalue()
        requests = Counter()
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests[self.path] += 1
                if self.path == '/index.json':
                    body = json.dumps({'version':'3.0.0','resources':[{'@id':address+'/flat/','@type':'PackageBaseAddress/3.0.0'}]}).encode()
                elif self.path == '/flat/fixture.cache/index.json':
                    body = b'{"versions":["1.0.0"]}'
                elif self.path.endswith('/fixture.cache.1.0.0.nupkg'):
                    body = data
                elif self.path.endswith('/fixture.cache.1.0.0.nupkg.sha512'):
                    body = base64.b64encode(hashlib.sha512(data).digest())
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Length',str(len(body)))
                self.send_header('Content-Type','application/octet-stream' if body==data else 'application/json')
                self.end_headers()
                self.wfile.write(body)
            def log_message(self,*args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        address = 'http://127.0.0.1:' + str(server.server_port)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory(prefix='nuget-cache-control-') as temporary:
            base=Path(temporary)
            source=base/'source';source.mkdir()
            cache=base/'http'
            (source/'NuGet.Config').write_text('<configuration><packageSources><clear/><add key="fixture" value="'+address+'/index.json" allowInsecureConnections="true"/></packageSources></configuration>')
            (source/'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net11.0</TargetFramework></PropertyGroup><ItemGroup><PackageReference Include="Fixture.Cache" Version="1.0.0"/></ItemGroup></Project>')
            (source/'Code.cs').write_text('public class C {}')
            command=[str(DOTNET),str(RUNNER),'nuget-update',str(source),str(SDK),'App.csproj','--distdir',str(base/'distdir')]
            home=base/'home'
            home.mkdir()
            environment=dict(os.environ, HOME=str(home), XDG_DATA_HOME=str(base/'data'))
            if sys.platform == 'darwin':
                # Foundation ignores HOME/XDG for LocalApplicationData. Keep its
                # native default inside this fixture rather than the user's home.
                environment['CFFIXED_USER_HOME']=str(home)
            if automatic is None:
                command+=['--no-http-cache']
            elif automatic:
                application_data=home/'Library/Application Support' if sys.platform == 'darwin' else base/'data'
                cache=application_data/'rules-msbuild/nuget-http'
            else:
                command+=['--http-cache',str(cache)]
            first=subprocess.run(command,text=True,capture_output=True,env=environment)
            self.assertEqual(first.returncode,0,first.stdout+first.stderr)
            expected={name:(source/name).read_bytes() for name in ['nuget.lock.json','packages.lock.json']}
            package_path='/flat/fixture.cache/1.0.0/fixture.cache.1.0.0.nupkg'
            self.assertEqual(requests[package_path],1)
            exported=base/'distdir/fixture.cache.1.0.0.nupkg'
            self.assertEqual(exported.read_bytes(),data)
            exported.unlink()
            second=subprocess.run(command+['--check'],text=True,capture_output=True,env=environment)
            self.assertEqual(second.returncode,0,second.stdout+second.stderr)
            self.assertEqual(requests[package_path],2 if automatic is None else 1,'acquisition did not follow the requested cache policy')
            self.assertEqual({name:(source/name).read_bytes() for name in expected},expected)
            self.assertEqual(bool(list(cache.rglob('nupkg_fixture.cache.1.0.0.dat'))),automatic is not None)
            self.assertFalse((source/'bin').exists())
            self.assertFalse((source/'obj').exists())
            self.assertEqual(exported.read_bytes(),data)
            exported.write_bytes(b'corrupt')
            rejected=subprocess.run(command+['--check'],text=True,capture_output=True,env=environment)
            self.assertNotEqual(rejected.returncode,0)
            self.assertIn('NuGet distdir archive differs',rejected.stderr)
            self.assertEqual(exported.read_bytes(),b'corrupt')


if __name__=='__main__':
    unittest.main()
