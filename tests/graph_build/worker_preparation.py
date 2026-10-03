"""Worker-owned preparation uses complete request identities, never manifest alone."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import tempfile

from qualify import DOTNET, ROOT, RUNNER


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache-mb', type=int, default=16)
    args = parser.parse_args()
    assert os.uname().sysname == 'Linux'
    with tempfile.TemporaryDirectory(prefix='graph-worker-preparation-') as temporary:
        root = Path(temporary)
        payload = root / 'input/prepared/.nuget/example/1.0.0/data'
        payload.parent.mkdir(parents=True)
        payload.write_bytes(b'original package')
        manifest = root / 'input/prepared/manifest.json'
        manifest.write_text(json.dumps({'Version': 1, 'Key': 'fixture', 'SdkDigest': 'fixture', 'Files': {
            '.nuget/example/1.0.0/data': {'Digest': hashlib.sha256(payload.read_bytes()).hexdigest(), 'Mode': 0o640}}}))
        # Model Bazel-normalized tree input modes; materialization restores 0640.
        payload.chmod(0o555)
        (root / 'contract.json').write_text('{"Projects":{}}')
        (root / 'request.json').write_text(json.dumps({'contract': 'contract.json', 'output': 'output',
            'target': 'Build', 'prepared': 'input', 'sources': []}))
        sandbox = root / 'inspect.sh'
        sandbox.write_text('''#!/bin/bash
set -eu
printf '%s\\n' "$8"
test "$(stat -c %a "$8/prepared/.nuget/example/1.0.0/data")" = 640
''')
        worker = subprocess.Popen([DOTNET, RUNNER, 'worker', sandbox, str(args.cache_mb), '--persistent_worker'],
            cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            def request(identity=True, success=True):
                shutil.rmtree(root / "output", ignore_errors=True)
                inputs = [{'path': str(p.relative_to(root)), 'digest': hashlib.sha256(p.read_bytes()).hexdigest() if identity else ''}
                          for p in [root / 'contract.json', root / 'request.json', manifest, payload]]
                worker.stdin.write(json.dumps({'arguments': ['request.json'], 'inputs': inputs, 'requestId': 1}) + '\n')
                worker.stdin.flush()
                reply = json.loads(worker.stdout.readline())
                assert (reply['exitCode'] == 0) == success, reply
                assert reply['requestId'] == 1, reply
                if success and args.cache_mb == 0:
                    assert not Path(reply['output'].strip()).exists(), 'Zero budget retained preparation'
                return reply['output'].strip()
            first = request()
            assert request() == first, 'Identical declared bytes did not reuse preparation'
            original = payload.read_bytes()
            payload.chmod(0o644)
            payload.write_bytes(b'corrupt input with unchanged manifest')
            assert 'Invalid prepared Restore file' in request(success=False)
            payload.write_bytes(original)
            payload.chmod(0o555)
            assert request() == first
            uncached = request(identity=False)
            assert uncached != first and request(identity=False) != uncached, 'Missing digests reused preparation'
            assert not list(Path(first).parent.glob('*.pending-*')), 'Failed preparation leaked pending data'
        finally:
            worker.stdin.close()
            worker.wait(timeout=30)
            assert worker.returncode == 0, worker.stderr.read()
        assert not Path(first).exists(), 'Worker-owned state survived normal broker exit'
        print('PASS: complete worker input identities, mode restoration, corrupt replacement rejection, no-digest fallback and cleanup')


if __name__ == '__main__':
    main()
