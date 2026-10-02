"""Build native controls directly from declared archives, without Bazel outputs."""
import json
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
import time

from timing_tools import verify_tools

w,out=[Path(p).resolve() for p in sys.argv[1:]]
out.mkdir(parents=True,exist_ok=False)
tools=verify_tools(cwd=out);sdk=Path(tools['sdkRoot']);here=Path(__file__).resolve().parent
manifest=json.loads((w/'subset.json').read_text())
packages=sorted({label.removeprefix('//').split(':')[0] for label in manifest['native'].values()})
driver=out/'driver';driver.mkdir()
shutil.copyfile(here/'NativeBuild.cs.txt',driver/'Program.cs')
shutil.copyfile(w/'native/Task.csproj',driver/'Task.csproj')
with (out/'driver.log').open('w') as log:subprocess.run([sdk/'dotnet','build',driver/'Task.csproj','-c','Release'],stdout=log,stderr=subprocess.STDOUT,check=True)
products=out/'products';products.mkdir();records=[]
for package in packages:
    inputs=w/package;folder=out/package;folder.mkdir()
    definitions=json.loads((inputs/'products.json').read_text())['products'] if (inputs/'products.json').exists() else {'coreclr':'libcoreclr.so','jit':'libclrjit.so','host':'corerun'}
    command=[sdk/'dotnet',driver/'bin/Release/net10.0/Task.dll',inputs/'bwrap',inputs/'toolchain.tar',inputs/'source.tar','/source/build-native.sh',folder/'runtime.tar',*[folder/name for name in definitions.values()]]
    begin=time.monotonic()
    with (folder/'build.log').open('w') as log:p=subprocess.run(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT,timeout=1800)
    row=dict(component=package,seconds=round(time.monotonic()-begin,3),exitCode=p.returncode,command=list(map(str,command)),sourceSha256=hashlib.sha256((inputs/'source.tar').read_bytes()).hexdigest())
    records.append(row);(out/'report.json').write_text(json.dumps(dict(toolchain=tools,records=records),indent=2)+'\n');p.check_returncode()
    row['products']={}
    for name in definitions.values():
        assert not (products/name).exists(),name
        shutil.copy2(folder/name,products/name);row['products'][name]=hashlib.sha256((products/name).read_bytes()).hexdigest()
    (out/'report.json').write_text(json.dumps(dict(toolchain=tools,records=records),indent=2)+'\n')
    print(package,row['seconds'],flush=True)
assert set(manifest['native'])<={p.name for p in products.iterdir()}
