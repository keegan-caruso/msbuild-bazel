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
        sources = []
        for index in range(12):
            source = root / ('source-' + str(index))
            source.write_text('authored-' + str(index))
            source.chmod(0o750 if index % 2 else 0o640)
            sources.append(dict(path=source.name, destination='authored/' + source.name))
        tree = root / 'tree/nested/file'
        tree.parent.mkdir(parents=True)
        tree.write_text('directory input')
        sources.append(dict(path='tree', destination='authored/tree'))
        request_path = root / 'request.json'
        request_data = json.loads(request_path.read_text())
        request_data['sources'] = sources
        request_path.write_text(json.dumps(request_data))
        sandbox = root / 'inspect.sh'
        sandbox.write_text('''#!/bin/bash
set -eu
printf '%s\\n' "$8"
test "$(stat -c %a "$8/prepared/.nuget/example/1.0.0/data")" = 640
if [[ $(sha256sum "$8/prepared/.nuget/example/1.0.0/data" | cut -d ' ' -f 1) != EXPECTED_DIGEST ]]; then
    echo 'Invalid prepared Restore file' >&2
    exit 1
fi
for index in {0..11}; do
    test "$(cat "$3/workspace/authored/source-$index")" = "authored-$index"
    expected=640; if (( index % 2 )); then expected=750; fi
    test "$(stat -c %a "$3/workspace/authored/source-$index")" = "$expected"
done
test "$(cat "$3/workspace/authored/tree/nested/file")" = 'directory input'
'''.replace('EXPECTED_DIGEST', hashlib.sha256(payload.read_bytes()).hexdigest()))
        worker = subprocess.Popen([DOTNET, RUNNER, 'worker', sandbox, str(args.cache_mb), '--persistent_worker'],
            cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            def request(identity=True, success=True, omit=None):
                shutil.rmtree(root / "output", ignore_errors=True)
                inputs = [{'path': str(p.relative_to(root)), 'digest': hashlib.sha256(p.read_bytes()).hexdigest() if identity else ''}
                          for p in [root / 'contract.json', root / 'request.json', manifest, payload,
                              *(root / ('source-' + str(i)) for i in range(12)), tree] if p != omit]
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
            assert 'Undeclared worker input' in request(success=False, omit=tree)
            assert request() == first
            request_data['sources'] = sources + [dict(path='source-0', destination='authored/source-1')]
            request_path.write_text(json.dumps(request_data))
            assert 'already exists' in request(success=False), 'Overlapping destinations did not fail closed'
            request_data['sources'] = sources
            request_path.write_text(json.dumps(request_data))
            assert request() == first
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
        print('PASS: staged file/tree bytes and modes, undeclared/overlapping input rejection, preparation identities, corruption, no-digest fallback and cleanup')


if __name__ == '__main__':
    main()
