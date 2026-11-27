"""Unix production broker cancellation, publication failure/retry and lease cleanup.

A controlled child replaces MSBuild, while the real broker, process supervisor,
request pump, staging, publication and lease implementation execute unchanged.
Bazel/MSBuild worker parity is covered separately by the integration suites.
"""
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import shutil
import subprocess
import tempfile
import time

from qualify import DOTNET, RUNNER


def main():
    assert os.uname().sysname in ('Linux', 'Darwin')
    with tempfile.TemporaryDirectory(prefix='worker-lifecycle-') as temporary:
        root = Path(temporary)
        (root / 'tmp').mkdir()
        (root / 'contract.json').write_text(json.dumps({'Projects': {'P.csproj': {
            'Inputs': [], 'OutputDirectories': ['owned']}}}))
        (root / 'request.json').write_text(json.dumps(dict(contract='contract.json', output='output', target='Build', sources=[])))
        (root / 'child.sh').write_text('''#!/bin/bash
set -eu
mkdir -p "$3/workspace/owned"
printf product > "$3/workspace/owned/product"
printf authored > "$3/workspace/private-input"
printf '%s\\n' "$5" > scratch-path
case "$(cat mode)" in
hang) printf '%s' "$$" > child-pid; touch ready; sleep 1000 ;;
link) ln -s /etc/passwd "$3/workspace/owned/hostile" ;;
fail) printf 'controlled failure' >&2; exit 17 ;;
esac
''')
        env = dict(os.environ, TMPDIR=str(root / 'tmp'))

        def start():
            return subprocess.Popen([DOTNET, RUNNER, 'worker', str(root / 'child.sh'), '16', '--persistent_worker'],
                                    cwd=root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)

        def send(worker, value):
            worker.stdin.write(json.dumps(value) + '\n')
            worker.stdin.flush()

        def request(worker, identity, mode):
            shutil.rmtree(root / 'output', ignore_errors=True)
            (root / 'mode').write_text(mode)
            send(worker, dict(arguments=['request.json'], requestId=identity, inputs=[
                dict(path=name, digest=hashlib.sha256((root / name).read_bytes()).hexdigest())
                for name in ['contract.json', 'request.json']]))

        def reply(worker):
            assert select.select([worker.stdout], [], [], 15)[0], 'Broker response timed out'
            return json.loads(worker.stdout.readline())

        def clean():
            assert not (root / 'output/.staging').exists(), 'Staging leaked'
            scratch = Path((root / 'scratch-path').read_text().strip())
            assert not scratch.exists(), 'Request scratch leaked'

        worker = start()
        try:
            request(worker, 1, 'hang')
            limit = time.monotonic() + 10
            while not (root / 'ready').exists():
                assert time.monotonic() < limit, 'Child did not start'
                time.sleep(.02)
            send(worker, dict(requestId=1, cancel=True))
            assert reply(worker)['wasCancelled']
            clean()
            assert not (root / 'output/workspace/owned/product').exists(), 'Cancelled product published'
            pid = int((root / 'child-pid').read_text())
            assert not Path('/proc', str(pid)).exists(), 'Cancelled child survived'
            for identity, mode in [(2, 'fail'), (3, 'link')]:
                request(worker, identity, mode)
                assert reply(worker)['exitCode'] != 0
                clean()
                assert not (root / 'output/workspace/owned/product').exists(), 'Failed product published'
            request(worker, 4, 'ok')
            assert reply(worker)['exitCode'] == 0
            clean()
            assert (root / 'output/workspace/owned/product').read_text() == 'product'
            assert not (root / 'output/workspace/private-input').exists(), 'Private input published'
            leases = root / 'tmp' / ('rules-msbuild-workers-' + str(os.geteuid()))
            assert len(list(leases.glob('*.lease'))) == 1
            # Kill an idle broker: no active child remains. Startup must reclaim
            # its abandoned state.
            worker.kill()
            worker.wait(timeout=10)
            worker = start()
            request(worker, 5, 'ok')
            assert reply(worker)['exitCode'] == 0
            assert len(list(leases.glob('*.lease'))) == 1, 'Abandoned lease not reclaimed'
            worker.stdin.close()
            assert worker.wait(timeout=10) == 0, worker.stderr.read()
            assert not list(leases.iterdir()), 'Normal broker exit leaked owned state'
        finally:
            try:
                os.killpg(worker.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            worker.wait(timeout=10)
        print('PASS: real broker live cancellation, child termination, failed publication isolation, clean retries, idle crash reclamation and normal lease cleanup')


if __name__ == '__main__':
    main()
