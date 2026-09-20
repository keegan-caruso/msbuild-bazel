"""Fresh Orchard workflows differing only in package copying versus borrowing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import urllib.request

from cache_service import CacheService
from workload import ROOT, remove, shutdown


def logical_package_bytes(binary):
    # FileInfo.Length in staging diagnostics can report a sandbox symlink's own
    # length. Follow declared package paths here to count actual payload bytes.
    execroot = binary.resolve().parents[2]
    sizes = {}
    total = 0
    for path in binary.glob('project_*.request.json'):
        request = json.loads(path.read_text())
        payload = json.loads((execroot / request['preparedPlan'] / 'payload.json').read_text())
        directories = {row['package']: execroot / row['source'] for row in request['packageDirectories']}
        explicit = {row['destination']: execroot / row['source'] for row in request['sources']}
        for name in payload:
            if not name.startswith('.nuget/packages/'):
                continue
            package, version, relative = name[len('.nuget/packages/'):].split('/', 2)
            source = explicit.get(name, directories[package + '/' + version] / relative)
            if source not in sizes:
                sizes[source] = source.stat().st_size
            total += sizes[source]
    return total


def application_check(app, output, sdk):
    runtime = output / 'runtime'
    shutil.copytree(app, runtime)
    for directory, _, _ in os.walk(runtime):
        os.chmod(directory, 0o700)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        url = 'http://127.0.0.1:' + str(sock.getsockname()[1])
    env = dict(os.environ, DOTNET_ROOT=sdk, ASPNETCORE_URLS=url,
               ASPNETCORE_ENVIRONMENT='Production')
    with (output / 'runtime.log').open('w') as log:
        process = subprocess.Popen([str(Path(sdk) / 'dotnet'), 'OrchardCore.Cms.Web.dll'],
                                   cwd=runtime, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(120):
                if process.poll() is not None:
                    raise RuntimeError('Orchard exited before HTTP validation')
                try:
                    with urllib.request.urlopen(url, timeout=5) as response:
                        html = response.read().decode()
                        assert response.status == 200
                        assert response.headers['X-Orchard-Cache-Probe'] == 'changed-csharp'
                        assert 'orchard-canonical-razor-change' in html
                    with urllib.request.urlopen(url + '/OrchardCore.Setup/Styles/setup.min.css', timeout=5) as response:
                        assert 'orchard-scoped-asset-change' in response.read().decode()
                    return dict(status=200, markers=['csharp', 'razor', 'css'])
                except OSError:
                    time.sleep(.5)
            raise RuntimeError('Orchard HTTP validation timed out')
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            remove(runtime)


def run(args):
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    original = json.loads(args.request.read_text())
    records = []
    first_hashes = None
    # Reuse the exact state path, removing it between runs; package archives and
    # the repository download cache remain warm. Each mode gets an empty cache.
    for mode in ['copy', 'borrow']:
        result = output / mode
        result.mkdir()
        with CacheService(args.cache_binary, output / (mode + '-cache'), max_size=8) as cache:
            request = dict(original, repository=str(ROOT), state=str(output / 'state'),
                           output=str(result / 'workflow'))
            request.update({'borrow-package-inputs': mode == 'borrow',
                            'bazel-remote-cache': cache.url, 'bazel-remote-upload': True})
            path = result / 'request.json'
            path.write_text(json.dumps(request, indent=2))
            try:
                with (result / 'command.log').open('w') as log:
                    process = subprocess.run([str(Path(request['sdkRoot']) / 'dotnet'),
                        str(ROOT / 'tools/Preparation/bin/Release/net10.0/Preparation.dll'),
                        'owned-workflow', '--request', str(path)], cwd=ROOT,
                        stdout=log, stderr=subprocess.STDOUT, timeout=2400)
                report = json.loads((result / 'workflow/report.json').read_text())
                assert process.returncode == 0 and report['accepted'], result
                assert report['compiles'] == args.projects, report['compiles']
                for mnemonic in ['MsbuildCompileProject', 'MsbuildBindProject',
                                 'MsbuildDiscover', 'MsbuildLockedRestore', 'NugetExtractPackage']:
                    assert report[mnemonic]['remoteHits'] == 0, (mode, mnemonic)
                binary = output / 'state/g/bazel-bin'
                phases = {}
                staging = []
                for diagnostics in binary.glob('project_*.diagnostics'):
                    for key, value in json.loads((diagnostics / 'timings.json').read_text()).items():
                        phases[key] = phases.get(key, 0) + value
                    staging.append(json.loads((diagnostics / 'staging.json').read_text()))
                assert len(staging) == args.projects
                assert all(row['borrowed'] == (mode == 'borrow') for row in staging)
                app = binary / 'build.bundle/app'
                hashes = {str(p.relative_to(app)): hashlib.sha256(p.read_bytes()).hexdigest()
                          for p in app.rglob('*') if p.is_file()}
                (result / 'application-hashes.json').write_text(json.dumps(hashes, indent=2))
                record = dict(mode=mode, seconds=report['seconds'], compiles=report['compiles'],
                              phases=report['phases'], compilePhaseTotals=phases,
                              packageFiles=sum(row['packageFiles'] for row in staging),
                              packageBytes=logical_package_bytes(binary),
                              packageStagingSeconds=sum(row['packageSeconds'] for row in staging),
                              payloadValidationSeconds=sum(row['validationSeconds'] for row in staging))
                if first_hashes is None:
                    first_hashes = hashes
                else:
                    assert hashes.keys() == first_hashes.keys(), 'Application membership changed'
                    different = [p for p in hashes if hashes[p] != first_hashes[p]]
                    record['applicationComparison'] = dict(files=len(hashes), different=different,
                                                          identical=len(hashes) - len(different))
                record['runtime'] = application_check(app, result, request['sdkRoot'])
                records.append(record)
                (output / 'report.json').write_text(json.dumps(records, indent=2))
                cache.capture('completed')
                print(json.dumps(record), flush=True)
            finally:
                shutdown(output)
        if mode == 'copy':
            remove(output / 'state')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache-binary', type=Path, required=True)
    parser.add_argument('--projects', type=int, default=202)
    run(parser.parse_args())
