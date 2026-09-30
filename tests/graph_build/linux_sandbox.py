"""The graph sandbox exposes its own processes, not the broker's /proc view."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

from qualify import ROOT


def main():
    assert os.uname().sysname == 'Linux'
    with tempfile.TemporaryDirectory(prefix='graph-sandbox-') as temporary:
        root = Path(temporary)
        for name in ['sdk', 'runner', 'output/workspace', 'scratch']:
            (root / name).mkdir(parents=True)
        (root / 'sdk/dotnet').write_text('''#!/bin/bash
set -eu
readlink /proc/self/ns/pid > /__rules_msbuild_graph/output/self-pid.txt
readlink /proc/1/ns/pid > /__rules_msbuild_graph/output/init-pid.txt
if touch /__rules_msbuild_graph/sdk/should-not-write 2>/dev/null; then exit 9; fi
''')
        (root / 'sdk/dotnet').chmod(0o755)
        (root / 'runner/GraphBuild.dll').write_text('sandbox entry point fixture')
        (root / 'contract.json').write_text('{}')
        host = os.readlink('/proc/self/ns/pid')
        subprocess.run(['bash', ROOT / 'msbuild/graph-sandbox.sh', root / 'sdk', root / 'runner', root / 'output',
                        root / 'contract.json', root / 'scratch', 'Build'], check=True)
        current = (root / 'output/self-pid.txt').read_text().strip()
        init = (root / 'output/init-pid.txt').read_text().strip()
        assert current == init and current != host, (host, current, init)
        assert not (root / 'sdk/should-not-write').exists()
        print(json.dumps({'host': host, 'sandbox': current}))
        print('PASS: separate PID namespace, matching private proc view and read-only SDK mount')


if __name__ == '__main__':
    main()
