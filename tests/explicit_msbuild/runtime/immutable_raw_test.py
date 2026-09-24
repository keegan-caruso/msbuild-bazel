"""Run upstream Immutable tests with a verified rebuilt assembly on the installed host."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import zipfile

source, folder, archive = map(lambda p: Path(p).resolve(), sys.argv[1:])
folder.mkdir(parents=True, exist_ok=False)
sdk = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
probe = folder/'probe'
probe.mkdir()
shutil.copyfile(Path(__file__).with_name('LoadProbe.cs.txt'), probe/'StartupHook.cs')
(probe/'Probe.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework></PropertyGroup></Project>')
with (folder/'probe-build.log').open('w') as log:
    subprocess.run([sdk/'dotnet','build',probe/'Probe.csproj','-c','Release'],stdout=log,stderr=subprocess.STDOUT,check=True)
host = folder/'host'
host.mkdir()
for relative in ['dotnet','host','shared/Microsoft.NETCore.App']:
    src=sdk/relative;dest=host/relative;dest.parent.mkdir(parents=True,exist_ok=True)
    if src.is_dir():shutil.copytree(src,dest,copy_function=os.link)
    else:os.link(src,dest)
frameworks=list((host/'shared/Microsoft.NETCore.App').iterdir());assert len(frameworks)==1 and frameworks[0].name=='10.0.11'
replacement=frameworks[0]/'System.Collections.Immutable.dll'
replacement.unlink()
raw=source/'artifacts/bin/System.Collections.Immutable/Release/net10.0/System.Collections.Immutable.dll'
shutil.copyfile(raw,replacement)
wrapper=host/'host.sh'
wrapper.write_text('#!/bin/sh\nset -eu\nexport DOTNET_ROOT='+shlex.quote(str(host))+'\nexport DOTNET_STARTUP_HOOKS='+shlex.quote(str(probe/'bin/Release/net10.0/Probe.dll'))+'\nexport QUALIFICATION_IMMUTABLE='+shlex.quote(str(replacement))+'\nexec '+shlex.quote(str(host/'dotnet'))+' "$@"\n')
wrapper.chmod(0o755)
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='3aabba2641a165f8274fbad94ed1c4e2a004877d37b2ddfab89962487f3dceab'
with zipfile.ZipFile(archive) as z:z.extractall(folder/'vstest')
tests=source/'artifacts/bin/System.Collections.Immutable.Tests/Release/net10.0'
proof=folder/'proof'
with (folder/'tests.log').open('w') as log:
    result=subprocess.run([wrapper,folder/'vstest/contentFiles/any/net9.0/vstest.console.dll',tests/'System.Collections.Immutable.Tests.dll','/Settings:'+str(tests/'.runsettings'),'/Logger:trx;LogFileName=results.trx','/ResultsDirectory:'+str(folder/'results'),'--','RunConfiguration.DotNetHostPath='+str(wrapper)],stdout=log,stderr=subprocess.STDOUT,env=dict(os.environ,TEST_UNDECLARED_OUTPUTS_DIR=str(proof)),timeout=900)
proofs=[json.loads(p.read_text()) for p in proof.glob('loaded-immutable-*.json')]
expected=hashlib.sha256(raw.read_bytes()).hexdigest().upper()
assert proofs and all(p['entry']=='testhost' and p['sha256']==expected for p in proofs),proofs
(folder/'report.json').write_text(json.dumps(dict(exitCode=result.returncode,loadedAssemblyProofs=proofs),indent=2)+'\n')
result.check_returncode()
