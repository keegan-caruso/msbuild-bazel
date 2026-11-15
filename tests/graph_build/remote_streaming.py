"""Bounded native CAS streaming, interrupted bodies and shared digest controls."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import time

from qualify import DOTNET, ROOT, run


class Cache(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *_):
        pass

    def do_GET(self):
        data = self.server.blobs.get(self.path)
        if data is None:
            self.send_response(404); self.send_header('Content-Length', '0'); self.end_headers()
            return
        large = len(data) > 1024 * 1024
        with self.server.lock:
            self.server.gets[self.path] = self.server.gets.get(self.path, 0) + 1
            if large:
                self.server.active += 1
                self.server.maximum = max(self.server.maximum, self.server.active)
            interrupt = large and self.server.interrupt
            if interrupt:
                self.server.interrupt = False
        try:
            self.send_response(200); self.send_header('Content-Length', str(len(data))); self.end_headers()
            if interrupt:
                self.wfile.write(data[:65536]); self.wfile.flush()
                self.close_connection = True
                return
            for offset in range(0, len(data), 65536):
                self.wfile.write(data[offset:offset+65536])
                if large:
                    time.sleep(.001)
        finally:
            with self.server.lock:
                if large:
                    self.server.active -= 1


def main():
    with tempfile.TemporaryDirectory(prefix='remote-streaming-') as temporary:
        work = Path(temporary)
        sources = [ROOT/'tools/ProjectCache'/name for name in ['RemoteSnapshotStore.cs', 'SnapshotPayloads.cs']]
        (work/'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'
            '<TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings>'
            '<Nullable>enable</Nullable></PropertyGroup><ItemGroup>' + ''.join(f'<Compile Include="{p}" />' for p in sources) + '</ItemGroup></Project>')
        (work/'Program.cs').write_text('''using RulesMSBuild.ProjectCache;
using System.Text.Json;
var shared = args[2] == "shared";
using var store = new RemoteSnapshotStore(new Uri(args[0]), parallelism: 2,
    contentStore: shared ? new SnapshotPayloads(Path.Combine(args[1], "payloads")) : null);
GC.Collect();
var baseline = GC.GetTotalMemory(true);
long peak = baseline;
using var timer = new Timer(_ => InterlockedExtensions(), null, 0, 2);
void InterlockedExtensions() { var value = GC.GetTotalMemory(false); long old; do { old = peak; if (value <= old) return; } while (Interlocked.CompareExchange(ref peak, value, old) != old); }
await Task.WhenAll(Enumerable.Range(0, 8).Select(i => store.FetchAsync("key" + i, Path.Combine(args[1], "snapshot" + i), CancellationToken.None)));
Console.WriteLine(JsonSerializer.Serialize(new { managedGrowth = peak - baseline }));
''')
        run(DOTNET, 'build', work/'Probe.csproj', '-c', 'Release')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Cache)
        server.blobs, server.gets, server.lock = {}, {}, threading.Lock()
        server.active, server.maximum, server.interrupt = 0, 0, True
        payloads = [bytes([i]) * (8*1024*1024) for i in range(8)]

        def seed(shared):
            server.blobs.clear(); server.gets.clear()
            for i in range(8):
                payload = payloads[0 if shared else i]
                digest = hashlib.sha256(payload).hexdigest()
                manifest = json.dumps({'Fingerprint': 'key'+str(i), 'Files': {'payload': digest}}).encode()
                md = hashlib.sha256(manifest).hexdigest()
                server.blobs['/cas/'+digest] = payload
                server.blobs['/cas/'+md] = manifest
                server.blobs['/rules-msbuild/ac/'+hashlib.sha256(('rules-msbuild-project-snapshot-v1\nkey'+str(i)).encode()).hexdigest()] = json.dumps({'outputFiles': [{'path':'manifest.json', 'digest': {'hash':md}}]}).encode()

        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            for shared in [False, True]:
                seed(shared)
                output = work/('shared' if shared else 'distinct')
                result = run(DOTNET, work/'bin/Release/net10.0/Probe.dll', f'http://127.0.0.1:{server.server_port}/', output, 'shared' if shared else 'distinct')
                observation = json.loads(result.stdout.strip().splitlines()[-1])
                assert observation['managedGrowth'] < 24*1024*1024, observation
                for i in range(8):
                    assert (output/f'snapshot{i}/payload').read_bytes() == payloads[0 if shared else i]
                if shared:
                    digest = hashlib.sha256(payloads[0]).hexdigest()
                    assert server.gets['/cas/'+digest] == 1, server.gets
                assert not list(output.rglob('*.download-*'))
                print('PASS:', 'shared' if shared else 'distinct', observation, 'peak_body_requests', server.maximum)
            assert server.maximum <= 2, server.maximum
            print('PASS: two global transfers; interrupted body retried; eight verified snapshots; shared digest one GET')
        finally:
            server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    main()
