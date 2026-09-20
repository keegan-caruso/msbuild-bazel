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

# An arbitrary input cannot be promoted into the startup tool trust boundary.
with tempfile.TemporaryDirectory() as directory:
    root=Path(directory); (root/'request.json').write_text('{}')
    for kind in ('sdk','runner'):
        manifest={'sdk':[],'runner':[]}; manifest[kind]=['request.json']
        (root/'tools.json').write_text(json.dumps(manifest))
        p=subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'),str(ROOT/'tools/ExplicitBuild/bin/Release/net10.0/ExplicitBuild.dll'),'--bazel-worker','--tool-inputs=tools.json','--persistent_worker'],
                         cwd=root,input='',capture_output=True,text=True,timeout=60)
        assert p.returncode==1 and 'outside its pinned root' in p.stderr,(kind,p.stdout,p.stderr)
    # A source symlink pointing into the SDK still needs a valid content digest.
    (root/'sdk-alias').symlink_to(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet')
    work=dict(arguments=['request.json'],inputs=[dict(path='sdk-alias',digest=base64.b64encode(b'0'*64).decode())],requestId=19)
    p=subprocess.run([str(Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])/'dotnet'),str(ROOT/'tools/ExplicitBuild/bin/Release/net10.0/ExplicitBuild.dll'),'--bazel-worker','--persistent_worker'],
                     cwd=root,input=json.dumps(work)+'\n',capture_output=True,text=True,timeout=60)
    reply=json.loads(p.stdout)
    assert p.returncode==0 and reply['exitCode']==1 and 'digest mismatch' in reply['output'],(p.stdout,p.stderr)
print('Tool inventory: rejected arbitrary tool roots and forged SDK-alias input.')
