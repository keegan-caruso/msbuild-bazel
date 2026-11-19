"""Project-cache publication controls using independent native client processes."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import time

from qualify import DOTNET, ENV, ROOT, run


class Cache(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def do_GET(self):
        with self.server.lock:
            data = self.server.blobs.get(self.path)
            barrier = self.server.barrier if '/ac/' in self.path and data is None else None
        if barrier is not None:
            barrier.wait(timeout=10)
        self.reply(404 if data is None else 200, data or b'')

    def do_PUT(self):
        data = self.rfile.read(int(self.headers['Content-Length']))
        if self.server.delay_upload:
            time.sleep(.5)
        with self.server.lock:
            self.server.puts += 1
            self.server.put_paths[self.path] = self.server.put_paths.get(self.path, 0) + 1
            if '/ac/' in self.path:
                if self.server.fail_pointer:
                    self.reply(503)
                    return
                result = json.loads(data)
                manifest = json.loads(self.server.blobs['/cas/' + result['outputFiles'][0]['digest']['hash']])
                assert all('/cas/' + digest in self.server.blobs for digest in manifest['Files'].values())
            self.server.blobs[self.path] = data
        self.reply(200)

    def reply(self, status, data=b''):
        self.send_response(status)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    with tempfile.TemporaryDirectory(prefix='project-publication-') as temporary:
        work = Path(temporary)
        sources = [ROOT / 'tools/ProjectCache/RemoteSnapshotStore.cs', ROOT / 'tools/GraphBuild/GraphRunOptions.cs']
        sources.append(ROOT / 'tools/RelativePathComponents.cs')
        (work / 'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFramework>net11.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings>'
            '<Nullable>enable</Nullable></PropertyGroup><ItemGroup>' +
            ''.join(f'<Compile Include="{path}" />' for path in sources) + '</ItemGroup></Project>')
        (work / 'Program.cs').write_text('''using RulesMSBuild.ProjectCache;
using RulesMSBuild.GraphBuild;
if (args[0] == "options")
{
    var options = GraphRunOptions.Read();
    Console.WriteLine(options.RemoteReadOnly);
    if (Environment.GetEnvironmentVariable("RULES_MSBUILD_PROJECT_CACHE_READ_ONLY") is not null) return 3;
    return 0;
}
using var store = new RemoteSnapshotStore(new Uri(args[1]), readOnly: args[0] == "readonly");
using var cancel = new CancellationTokenSource(args[0] == "cancel" ? 100 : 30000);
try
{
    if (args[0] == "pair")
    {
        await Task.WhenAll(store.PublishAsync("pair-left", Path.Combine(args[3], "pair-left"), cancel.Token),
            store.PublishAsync("pair-right", Path.Combine(args[3], "pair-right"), cancel.Token));
        return 0;
    }
    Console.WriteLine(args[0] == "fetch"
        ? await store.FetchAsync(args[2], args[3], cancel.Token)
        : await store.PublishAsync(args[2], args[3], cancel.Token));
    return 0;
}
catch (OperationCanceledException) { return 2; }
''')
        run(DOTNET, 'build', work / 'Probe.csproj', '-c', 'Release')
        program = work / 'bin/Release/net11.0/Probe.dll'
        server = ThreadingHTTPServer(('127.0.0.1', 0), Cache)
        server.blobs, server.lock, server.puts = {}, threading.Lock(), 0
        server.put_paths = {}
        server.barrier, server.fail_pointer, server.delay_upload = None, False, False
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f'http://127.0.0.1:{server.server_port}/'

        def probe(mode, key, path, success=True):
            return run(DOTNET, program, mode, url, key, path, success=success)

        def snapshot(name, key, payload):
            path = work / name
            path.mkdir()
            (path / 'payload').write_bytes(payload)
            (path / 'manifest.json').write_text(json.dumps({'Fingerprint': key, 'Files': {
                'payload': hashlib.sha256(payload).hexdigest()}}))
            return path

        try:
            source = snapshot('source', 'same', b'identical publication')
            # Force two independent clients to observe the absent pointer together.
            server.barrier = threading.Barrier(2)
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda _: probe('publish', 'same', source), range(2)))
            server.barrier = None
            destination = work / 'fetched'
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda _: probe('fetch', 'same', destination), range(2)))
            assert (destination / 'payload').read_bytes() == b'identical publication'
            assert not list(work.glob('fetched.fetch-*'))
            print('PASS: independent identical writers and concurrent complete readers')

            payload = b'one upload across distinct snapshots' * 10000
            snapshot('pair-left', 'pair-left', payload)
            snapshot('pair-right', 'pair-right', payload)
            probe('pair', 'unused', work)
            digest = hashlib.sha256(payload).hexdigest()
            assert server.put_paths['/cas/' + digest] == 1, server.put_paths
            probe('fetch', 'pair-left', work / 'pair-left-fetch')
            probe('fetch', 'pair-right', work / 'pair-right-fetch')
            assert (work / 'pair-right-fetch/payload').read_bytes() == payload
            print('PASS: overlapping distinct-key publications share one verified payload PUT')

            # Divergence is detectable when publications are serialized. Ordinary
            # HTTP AC has no compare-and-swap guarantee for divergent racing writers.
            changed = snapshot('changed', 'same', b'divergent bytes')
            pointers = {k: v for k, v in server.blobs.items() if '/ac/' in k}
            assert 'Conflicting project-cache outputs' in probe('publish', 'same', changed, success=False).stderr
            assert {k: v for k, v in server.blobs.items() if '/ac/' in k} == pointers
            puts = server.puts
            assert probe('readonly', 'same', changed).stdout.strip() == 'False'
            assert probe('readonly', 'absent', work / 'no-source-required').stdout.strip() == 'False'
            assert server.puts == puts
            print('PASS: serialized divergence rejection; explicit read-only consumers send no PUT')

            left = snapshot('left', 'unsupported-race', b'left divergent output')
            right = snapshot('right', 'unsupported-race', b'right divergent output')
            server.barrier = threading.Barrier(2)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda source: probe('publish', 'unsupported-race', source), [left, right]))
            server.barrier = None
            assert all(result.stdout.strip() == 'True' for result in results)
            probe('fetch', 'unsupported-race', work / 'raced')
            assert (work / 'raced/payload').read_bytes() in {b'left divergent output', b'right divergent output'}
            print('LIMIT: divergent racing writers both publish; external serialization is required')

            interrupted = snapshot('interrupted', 'interrupted', b'unpublished payload')
            server.fail_pointer = True
            probe('publish', 'interrupted', interrupted, success=False)
            server.fail_pointer = False
            assert probe('fetch', 'interrupted', work / 'missing').stdout.strip() == 'False'
            assert not (work / 'missing').exists()
            probe('publish', 'interrupted', interrupted)
            assert probe('fetch', 'interrupted', work / 'repaired').stdout.strip() == 'True'
            print('PASS: failed pointer publication exposes no snapshot; serialized retry repairs it')

            cancelled = snapshot('cancelled', 'cancelled', b'cancelled payload')
            server.delay_upload = True
            result = subprocess.run([str(DOTNET), str(program), 'cancel', url, 'cancelled', str(cancelled)], env=ENV)
            assert result.returncode == 2, result.returncode
            time.sleep(.6)
            server.delay_upload = False
            assert probe('fetch', 'cancelled', work / 'cancelled-fetch').stdout.strip() == 'False'
            assert not list(work.glob('cancelled-fetch.fetch-*'))
            print('PASS: cancellation before pointer publication leaves no visible entry')

            for value, expected in [('0', 'False'), ('1', 'True')]:
                result = subprocess.run([str(DOTNET), str(program), 'options'], env=dict(ENV,
                    RULES_MSBUILD_PROJECT_CACHE_READ_ONLY=value), text=True, capture_output=True)
                assert result.returncode == 0 and result.stdout.strip() == expected, result
            invalid = subprocess.run([str(DOTNET), str(program), 'options'], env=dict(ENV,
                RULES_MSBUILD_PROJECT_CACHE_READ_ONLY='yes'), text=True, capture_output=True)
            assert invalid.returncode != 0 and 'must be 0 or 1' in invalid.stderr
            print('PASS: strict consumer-mode parsing and child-environment removal')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == '__main__':
    main()
