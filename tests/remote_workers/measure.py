"""Repeated .NET native remote-cache versus ordinary MSBuild; real cache service."""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import subprocess
from cache_service import CacheService,PIN
from workload import fixture,mutate,native,raw,remove,shutdown,ROOT

CASES=('unchanged','body','api','empty')

def run(args):
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    protocol=(args.protocol or ROOT/'docs/dotnet-worker-measurement-protocol.md').read_text()
    (output/'protocol.md').write_text(protocol)
    report=dict(accepted=False,scope='same-host real-service timing; not independent-worker qualification',
                revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                repetitions=args.repetitions,sharedBazelInstall=args.bazel_install_cache is not None,sharedBazelRepository=args.bazel_repository_cache is not None,service=PIN,producers=[],samples=[],medians=[],
                harnessSha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')})
    def save():(output/'report.json').write_text(json.dumps(report,indent=2))
    try:
        for kind in args.workloads:
            root=output/kind;root.mkdir()
            with CacheService(args.cache_binary,root/'server') as service:
                producer=root/'producer'/'n';source=fixture(producer,kind,args.packages,args.checkout)
                try:p=native(producer,source,kind,args.packages,service.url+'/native',install_cache=args.bazel_install_cache,repository_cache=args.bazel_repository_cache)
                finally:shutdown(producer)
                report['producers'].append(dict(kind=kind,result=p))
                key=p['remote']['publishedSnapshot'];remove(producer)
                for repetition in range(args.repetitions):
                    for case in args.cases:
                        base=root/(case+'-'+str(repetition));ns=fixture(base/'n',kind,args.packages,args.checkout);rs=fixture(base/'r',kind,args.packages,args.checkout)
                        if case!='empty':raw(base/'r',rs,kind,args.packages,label='warmup',test=False)
                        mutate(ns,kind,case);mutate(rs,kind,case)
                        assert not (base/'n/state').exists()
                        selected=None if case=='empty' else key
                        alternate=CacheService(args.cache_binary,base/'server') if case=='empty' else None
                        endpoint=alternate.__enter__().url+'/native' if alternate else service.url+'/native'
                        try:
                            if repetition%2:
                                n=native(base/'n',ns,kind,args.packages,endpoint,selected,install_cache=args.bazel_install_cache,repository_cache=args.bazel_repository_cache);r=raw(base/'r',rs,kind,args.packages)
                            else:
                                r=raw(base/'r',rs,kind,args.packages);n=native(base/'n',ns,kind,args.packages,endpoint,selected,install_cache=args.bazel_install_cache,repository_cache=args.bazel_repository_cache)
                            if args.bazel_install_cache:
                                assert 'Extracting Bazel installation' not in (base/'n/result/bazel.log').read_text()
                            expected=0 if case=='unchanged' else 1 if case=='body' else (4 if kind=='diamond' else 2) if case=='api' else (4 if kind=='diamond' else 2)
                            assert n['compiles']==expected,(kind,case,n['compiles'],expected)
                            assert r['compiles']==0 if case=='unchanged' else r['compiles']>=1,(kind,case,r['compiles'])
                            assert n['managedHashes']==r['managedHashes'],(kind,case,'runtime/PDB parity failed',n['managedHashes'],r['managedHashes'])
                            if kind=='diamond':assert n['applicationOutput']==r['applicationOutput']
                            value=dict(kind=kind,case=case,repetition=repetition,raw=r,native=n,ratio=n['wallSeconds']/r['seconds'])
                            report['samples'].append(value);save()
                            print(kind,case,repetition,'raw',round(r['seconds'],3),'native',round(n['wallSeconds'],3),'compiles',n['compiles'],flush=True)
                        finally:
                            shutdown(base/'n')
                            if alternate:alternate.capture('final');alternate.__exit__(None,None,None)
                service.capture('final')
        for kind in args.workloads:
            for case in args.cases:
                samples=[s for s in report['samples'] if s['kind']==kind and s['case']==case]
                ordinary=statistics.median(s['raw']['seconds'] for s in samples);adapter=statistics.median(s['native']['wallSeconds'] for s in samples)
                transport={key:statistics.median(s['native']['remote']['transport'][key] for s in samples) for key in samples[0]['native']['remote']['transport']}
                phases={key:statistics.median(s['native']['phases'].get(key,0) for s in samples) for key in set().union(*(s['native']['phases'] for s in samples))}
                report['medians'].append(dict(kind=kind,case=case,rawSeconds=ordinary,nativeSeconds=adapter,ratio=adapter/ordinary,transport=transport,phases=phases,
                    withinDiagnosticTarget=adapter<=1.25*ordinary+.250 if case!='empty' else None))
        report['accepted']=True
    finally:save()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('output','cache-binary','packages','checkout'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--repetitions',type=int,default=3)
    parser.add_argument('--protocol',type=Path)
    parser.add_argument('--bazel-repository-cache',type=Path)
    parser.add_argument('--bazel-install-cache',type=Path)
    parser.add_argument('--cases',nargs='+',choices=CASES,default=CASES)
    parser.add_argument('--workloads',nargs='+',choices=['diamond','serilog'],default=['diamond','serilog'])
    args=parser.parse_args()
    if args.repetitions<1:parser.error('repetitions must be positive')
    run(args)
