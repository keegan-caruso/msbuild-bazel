"""Paired off/on integrity profiles on unchanged reused workers, plus fresh/edit diagnostics."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from cache_service import CacheService
from workload import ROOT,fixture,native,mutate,raw,remove,shutdown


def run(a):
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(accepted=False,revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),samples=[])
    def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    try:
        for kind in ['diamond','serilog']:
            root=out/kind;root.mkdir()
            with CacheService(a.cache_binary,root/'server') as server:
                def invoke(base,source,snapshot=None,upload=False,profile=False):
                    return native(base,source,kind,a.packages,server.url+'/native',snapshot,install_cache=a.bazel_install_cache,repository_cache=a.bazel_repository_cache,action_cache=server.url,action_upload=upload,integrity_profile=profile)
                producer=root/'producer';source=fixture(producer,kind,a.packages,a.checkout)
                try:p=invoke(producer,source,upload=True)
                finally:shutdown(producer)
                snapshot=p['remote']['publishedSnapshot'];expected=p['managedHashes'];remove(producer)
                base=root/'consumer';source=fixture(base,kind,a.packages,a.checkout)
                try:
                    first=invoke(base,source,snapshot,profile=True);assert first['remoteBuildHits']==1 and first['compiles']==0 and first['managedHashes']==expected
                    report['samples'].append(dict(kind=kind,case='fresh-hit',profile=True,repetition=0,result=first));(base/'result').rename(base/'fresh-result');save()
                    for rep in range(3):
                        for profile in ([False,True] if rep%2==0 else [True,False]):
                            value=invoke(base,source,snapshot,profile=profile)
                            assert value['compiles']==0 and value['managedHashes']==expected
                            assert value['worker']==first['worker'] and value['leaseVerification']==first['leaseVerification']
                            assert ('integrityProfile' in value)==profile
                            report['samples'].append(dict(kind=kind,case='reused-hit',profile=profile,repetition=rep,result=value));save()
                            (base/'result').rename(base/f'result-{rep}-{profile}')
                            print(kind,rep,profile,round(value['phases']['identity'],3),round(value['phases']['leaseExit'],3),flush=True)
                    mutate(source,kind,'body');value=invoke(base,source,snapshot,profile=True);assert value['compiles']==1
                    rb=root/'raw-edited';rs=fixture(rb,kind,a.packages,a.checkout);mutate(rs,kind,'body');ordinary=raw(rb,rs,kind,a.packages)
                    assert value['managedHashes']==ordinary['managedHashes']
                    report['samples'].append(dict(kind=kind,case='reused-edit',profile=True,repetition=0,result=value));save()
                finally:
                    # shutdown reads the last report to retain the selected install base
                    shutdown(base)
                server.capture('final')
        report['accepted']=True
    finally:save()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ['output','cache-binary','packages','checkout','bazel-install-cache','bazel-repository-cache']:p.add_argument('--'+n,type=Path,required=True)
    run(p.parse_args())
