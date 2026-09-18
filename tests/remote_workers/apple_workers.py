"""Orchestrate producer deletion and recovery in two independent Linux VMs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import uuid

ROOT=Path(__file__).resolve().parents[2]
CACHE='docker.io/buchgr/bazel-remote-cache@sha256:8109f1f39eb17d898cf51e08b41e4eabaaaeb1f584c2f22c1be45b7568fcc512'
GUEST=r'''set -euo pipefail
mkdir /controller
tar -xf /input/source.tar -C /controller
cd /controller
export DOTNET_CLI_TELEMETRY_OPTOUT=1 DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1
for project in tools/*/*.csproj tests/Preparation.Tests/*.csproj tests/ActionRunner.Tests/*.csproj; do
    bash scripts/dotnet.sh build "$project" -c Release --nologo
done
bash scripts/dotnet.sh tests/ActionRunner.Tests/bin/Release/net10.0/ActionRunner.Tests.dll
python3 -m unittest discover -s tests/dotnet_workflow -v
python3 -m unittest discover -s tests/dotnet_preparation -v
git init -q /upstream
git -C /upstream remote add origin https://github.com/serilog/serilog.git
git -C /upstream fetch --depth 1 origin 49b5339ce85385dc52d4d8e8f2b8308becf23506
git -C /upstream checkout -q FETCH_HEAD
role="$1"; endpoint="$2"
args=()
if [[ "$role" == consume ]]; then args+=(--handoff /handoff/producer.json); fi
# Only reports/logs are exported. Build state remains on this VM's private disk.
trap 'cp /runs/qualified/report.json /evidence/report.json 2>/dev/null || true; find /runs -type f -name "*.log" -exec cp --parents {} /evidence/ \; 2>/dev/null || true' EXIT
python3 tests/remote_workers/linux_worker.py "$role" --output /runs/qualified --packages /packages \
    --checkout /upstream --endpoint "$endpoint" "${args[@]}"
'''


def run(args):
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    inputs=output/'input';inputs.mkdir();handoff=output/'handoff';handoff.mkdir()
    files=subprocess.check_output(['git','ls-files','-z','--cached','--others','--exclude-standard'],cwd=ROOT).decode().split('\0')
    with tarfile.open(inputs/'source.tar','w') as archive:
        for name in sorted(set(files)-{''}):archive.add(ROOT/name,arcname=name,recursive=False)
    token='msbuild-workers-'+uuid.uuid4().hex[:8]
    cache=token+'-cache';active=[]
    report=dict(accepted=False,scope='separate Linux VMs on one physical Mac',image=args.image,cacheImage=CACHE,
                sourceArchiveSha256=hashlib.sha256((inputs/'source.tar').read_bytes()).hexdigest(),
                revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    def command(*arguments,**kwargs):return subprocess.run(['container',*arguments],check=True,text=True,**kwargs)
    def inspect(name):return json.loads(command('inspect',name,capture_output=True).stdout)[0]
    def delete(name):
        command('stop',name,capture_output=True);command('delete',name,capture_output=True);active.remove(name)
    try:
        command('run','-d','--name',cache,'--cpus','1','--memory','256M','--entrypoint','/bazel-remote-linux-arm64',CACHE,
                '--dir','/data','--max_size','2','--http_address','0.0.0.0:8080','--grpc_address','none','--profile_address','none','--enable_endpoint_metrics')
        active.append(cache);report['cache']=inspect(cache)
        endpoint='http://'+report['cache']['status']['networks'][0]['ipv4Address'].split('/')[0]+':8080'
        for role in ('produce','consume'):
            evidence=output/role;evidence.mkdir();name=token+'-'+role
            command('run','-d','--name',name,'--init','--cpus','4','--memory','6G','--masked-path','NONE','--read-only-path','NONE',
                    '-v',str(inputs)+':/input:ro','-v',str(handoff)+':/handoff:ro','-v',str(evidence)+':/evidence',args.image,'sleep','infinity')
            active.append(name);report[role+'Container']=inspect(name)
            with (evidence/'run.log').open('w') as log:
                command('exec','-i',name,'bash','-s','--',role,endpoint,input=GUEST,stdout=log,stderr=subprocess.STDOUT)
            result=json.loads((evidence/'report.json').read_text());assert result['accepted']
            report[role]=result
            delete(name)
            if role=='produce':
                absent=subprocess.run(['container','inspect',name],capture_output=True).returncode!=0
                assert absent,'Producer VM still exists'
                report['producerDeletedBeforeConsumer']=True
                (handoff/'producer.json').write_text(json.dumps(result))
        assert report['produce']['bootIdHash']!=report['consume']['bootIdHash']
        report['accepted']=True
    finally:
        for name in reversed(active[:]):
            try:delete(name)
            except subprocess.CalledProcessError:pass
        (output/'report.json').write_text(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',required=True)
    parser.add_argument('--output',type=Path,required=True)
    run(parser.parse_args())
