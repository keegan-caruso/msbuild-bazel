"""Strict raw/Bazel Immutable API parity with a pinned APICompat tool."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.request
import zipfile

source, workspace, folder = map(lambda p:Path(p).resolve(),sys.argv[1:])
folder.mkdir(parents=True,exist_ok=False)
data=urllib.request.urlopen('https://api.nuget.org/v3-flatcontainer/microsoft.dotnet.apicompat.tool/10.0.400/microsoft.dotnet.apicompat.tool.10.0.400.nupkg').read()
expected='c972c16992e1816dd22ca8029bbc96cdf9eb4f9f38550ca609e362ca5bc76eac'
assert hashlib.sha256(data).hexdigest()==expected
archive=folder/'apicompat.nupkg';archive.write_bytes(data)
with zipfile.ZipFile(archive) as z:z.extractall(folder/'tool')
api=folder/'tool/tools/net8.0/any/Microsoft.DotNet.ApiCompat.Tool.dll'
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
references=','.join(str(source/path) for path in ['artifacts/bin/microsoft.netcore.app.ref/ref/net10.0','artifacts/bin/System.Private.CoreLib/ref/Release/net10.0'])
records=[]
for kind,raw_path,bazel_path in [
    ('contract','ref/Release/net10.0','src_libraries_System.Collections.Immutable_ref_System.Collections.Immutable_net10.0.reference'),
    ('implementation','Release/net10.0','src_libraries_System.Collections.Immutable_src_System.Collections.Immutable_net10.0.runtime'),
]:
    left=source/'artifacts/bin/System.Collections.Immutable'/raw_path/'System.Collections.Immutable.dll'
    right=workspace/'bazel-bin/upstream'/bazel_path/'System.Collections.Immutable.dll'
    with (folder/(kind+'.log')).open('w') as log:
        result=subprocess.run([sdk/'dotnet',api,'-l',left,'-r',right,'--lref',references,'--rref',references,'--strict-mode','--enable-rule-attributes-must-match','--enable-rule-cannot-change-parameter-name'],stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,DOTNET_ROLL_FORWARD='Major'),timeout=120)
    result.check_returncode()
    records.append(dict(kind=kind,exitCode=result.returncode,leftSha256=hashlib.sha256(left.read_bytes()).hexdigest(),rightSha256=hashlib.sha256(right.read_bytes()).hexdigest()))
(folder/'report.json').write_text(json.dumps(dict(tool='Microsoft.DotNet.ApiCompat.Tool/10.0.400',archiveSha256=expected,strictMode=True,attributesMustMatch=True,parameterNamesMustMatch=True,comparisons=records),indent=2)+'\n')
print(json.dumps(records),flush=True)
