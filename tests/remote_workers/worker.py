"""Run one side of acceptance on a real worker; pass only the handoff JSON to B."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from workload import fixture,native,remove,shutdown


def machine_id():
    # Retain only a one-way digest, never the platform UUID/serial inventory.
    text=subprocess.check_output(['/usr/sbin/ioreg','-rd1','-c','IOPlatformExpertDevice'],text=True)
    match=re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"',text)
    if not match:raise RuntimeError('Cannot identify independent worker')
    return hashlib.sha256(match.group(1).encode()).hexdigest()


def run(args):
    base=args.output.resolve();identity=machine_id()
    handoff=json.loads(args.handoff.read_text()) if args.handoff else None
    if args.role=='consume':
        if handoff is None:raise ValueError('consumer requires handoff')
        if handoff['kind']!=args.kind:raise ValueError('handoff workload differs')
        if not handoff['producerRemoved']:raise ValueError('producer cleanup not certified')
        if identity==handoff['machineIdHash'] and not args.allow_same_host:raise ValueError('Independent acceptance requires different machines')
    source=fixture(base,args.kind,args.packages,args.checkout)
    initial=dict(stateAbsent=not (base/'state').exists(),source=str(source),machineIdHash=identity)
    assert initial['stateAbsent']
    try:
        result=native(base,source,args.kind,args.packages,args.endpoint,handoff['snapshot'] if handoff else None)
        expected=0 if handoff else 4 if args.kind=='diamond' else 2
        assert result['compiles']==expected,result
        if handoff:
            assert result['worker']==handoff['worker'],result['worker']
            assert result['managedHashes']==handoff['managedHashes'],'Recovered managed outputs differ'
            assert result['remote']['transport']['getRequests']>0
        evidence=dict(accepted=True,role=args.role,kind=args.kind,machineIdHash=identity,
                      independentMachines=handoff is not None and identity!=handoff['machineIdHash'],
                      initial=initial,result=result)
        (base/'evidence.json').write_text(json.dumps(evidence,indent=2))
    finally:shutdown(base)
    if args.role=='produce':
        remove(base/'state');remove(source)
        assert not (base/'state').exists() and not source.exists()
        handoff=dict(kind=args.kind,machineIdHash=identity,producerRemoved=True,
                     snapshot=result['remote']['publishedSnapshot'],worker=result['worker'],managedHashes=result['managedHashes'])
        (base/'handoff.json').write_text(json.dumps(handoff,indent=2))
    print(json.dumps(evidence,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role',choices=['produce','consume'])
    parser.add_argument('--kind',choices=['diamond','serilog'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--packages',type=Path,required=True)
    parser.add_argument('--checkout',type=Path)
    parser.add_argument('--endpoint',required=True)
    parser.add_argument('--handoff',type=Path)
    parser.add_argument('--allow-same-host',action='store_true',help='Rehearsal only; never marks independentMachines true')
    run(parser.parse_args())
