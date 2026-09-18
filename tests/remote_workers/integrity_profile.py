"""Profile the same resolved SDK closure used by NativeWorkflow."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import statistics
import subprocess

ROOT=Path(__file__).resolve().parents[2]


def run(output,label):
    output.mkdir(parents=True,exist_ok=False)
    # Resolve the wrapper exactly as Host.Real does before querying its closure.
    sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']).resolve()
    roots=sorted(subprocess.check_output(['/nix/var/nix/profiles/default/bin/nix-store','-qR',str(sdk.parents[1])],text=True).splitlines())
    request=output/'request.json';request.write_text(json.dumps(dict(roots=roots)))
    process=subprocess.run([str(sdk/'dotnet'),str(ROOT/'tests/Preparation.Tests/bin/Release/net10.0/Preparation.Tests.dll'),
        'integrity-profile',str(request)],capture_output=True,text=True,check=True)
    report=json.loads(process.stdout)
    report.update(label=label,roots=len(roots),revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  assemblySha256=hashlib.sha256((ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll').read_bytes()).hexdigest())
    samples=report['samples']
    report['medians']={phase:{field:statistics.median(s['phases'][phase][field] for s in samples) for field in ('seconds','allocatedBytes')} for phase in samples[0]['phases']}
    report['medianCollections']=[statistics.median(s['collections'][g] for s in samples) for g in range(3)]
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(roots=report['roots'],files=samples[0]['files'],contentBytes=samples[0]['contentBytes'],medians=report['medians'],collections=report['medianCollections']),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--label',required=True)
    args=parser.parse_args();run(args.output,args.label)
