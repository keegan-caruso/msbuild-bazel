"""Linux broker rejects forged digests and continues serving the next request."""
import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory); (root/'request.json').write_text('{}')
    requests=[dict(arguments=['request.json'],inputs=[dict(path='request.json',digest=base64.b64encode(b'0'*64).decode())],requestId=17),
              dict(arguments=['request.json'],inputs=[],requestId=18)]
    p=subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'),str(ROOT/'tools/ExplicitBuild/bin/Release/net10.0/ExplicitBuild.dll'),'--bazel-worker','--persistent_worker'],
                     cwd=root,input=''.join(json.dumps(r)+'\n' for r in requests),capture_output=True,text=True,timeout=60)
    assert p.returncode==0,p.stderr
    replies=[json.loads(line) for line in p.stdout.splitlines()]
    assert [r['requestId'] for r in replies]==[17,18],replies
    assert all(r['exitCode']==1 for r in replies),replies
    assert 'digest mismatch' in replies[0]['output'],replies
    assert 'Undeclared worker input' in replies[1]['output'],replies
    print('Worker protocol: rejected forged digest and undeclared request; broker recovered.')
