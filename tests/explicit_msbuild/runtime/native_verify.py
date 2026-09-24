"""Compare upstream cases and prove the runtime actually loaded Bazel outputs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
workspace, raw, report = [Path(p).resolve() for p in sys.argv[1:]]
subprocess.run([sys.executable,Path(__file__).with_name('immutable_verify.py'),workspace,raw,report],check=True,stdout=subprocess.DEVNULL)
result=json.loads(report.read_text())
corelib='src_coreclr_System.Private.CoreLib_System.Private.CoreLib_net10.0'
commit=b'60629d14374c56f1cb51819049ad1fa529307f8d'
for name in ['libcoreclr.so','libclrjit.so','corerun']:
    assert commit in (workspace/'bazel-bin/native/runtime.generated'/name).read_bytes(),('Missing pinned native commit stamp',name)
expected={name:hashlib.sha256((workspace/'bazel-bin/native/runtime.generated'/name).read_bytes()).hexdigest().upper() for name in ['libcoreclr.so','libclrjit.so']}
expected['System.Private.CoreLib.dll']=hashlib.sha256((workspace/'bazel-bin/upstream'/(corelib+'.runtime/System.Private.CoreLib.dll')).read_bytes()).hexdigest().upper()
proofs={}
for label in ['upstream/src_libraries_System.Collections.Immutable_tests_System.Collections.Immutable.Tests_net10.0','smoke/smoke']:
    output=workspace/'bazel-testlogs'/label/'test.outputs'
    rows=[json.loads(p.read_text()) for p in output.glob('loaded-*.json')]
    if (output/'outputs.zip').is_file():
        with zipfile.ZipFile(output/'outputs.zip') as archive:
            rows += [json.loads(archive.read(n)) for n in archive.namelist() if n.startswith('loaded-') and n.endswith('.json')]
    native=[row for row in rows if Path(row['path']).name in expected]
    assert {Path(row['path']).name for row in native}==set(expected),(label,rows)
    assert all(row['sha256']==expected[Path(row['path']).name] for row in native),(label,native,expected)
    proofs[label]=native
result.update(sourceBuiltCoreCLR=True,nativeRuntime='CoreCLR/JIT/CoreLib v10.0.0 source; installed 10.0.11 hostfxr and remaining framework',nativeBinaryHashes=expected,loadedNativeProofs=proofs)
report.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'testCount':result['testCount'],'nativeBinaryHashes':expected}),flush=True)
