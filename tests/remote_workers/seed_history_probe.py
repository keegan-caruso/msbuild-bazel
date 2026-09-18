"""Prove same-source seeds and outer keys converge across different build histories."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import urllib.request
from cache_service import CacheService
from workload import fixture, native, mutate, shutdown, remove, ROOT, BAZEL


def run(args):
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    report=dict(accepted=False,revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),cases=[])
    def save():(output/'report.json').write_text(json.dumps(report,indent=2))
    try:
        with CacheService(args.cache_binary,output/'server') as server:
            def build(label,snapshot=None,body=False,upload=True,bazel=None):
                base=output/label;source=fixture(base,'serilog',args.packages,args.checkout)
                if body:mutate(source,'serilog','body')
                try:
                    result=native(base,source,'serilog',args.packages,server.url+'/native',snapshot,
                                  install_cache=args.bazel_install_cache,repository_cache=args.bazel_repository_cache,
                                  action_cache=server.url,action_upload=upload,bazel_override=bazel)
                finally:shutdown(base)
                report['cases'].append(dict(case=label,result=result));save()
                print(label,result['compiles'],result['remoteBuildHits'],result.get('cachePrime'),flush=True)
                return result
            original=build('original');key=original['remote']['publishedSnapshot'];remove(output/'original')
            assert original['cachePrime']['accepted'] and original['cachePrime']['compiles']==0
            history=build('edited-history',key,True);historyKey=history['remote']['publishedSnapshot']
            assert history['compiles']==1 and history['cachePrime']['accepted']
            remove(output/'edited-history')
            cold=build('edited-cold',body=True);coldKey=cold['remote']['publishedSnapshot']
            assert cold['compiles']==2 and cold['cachePrime']['remoteBuildHits']==1,cold.get('cachePrime')
            assert cold['managedHashes']==history['managedHashes']
            remove(output/'edited-cold')
            def projects(snapshot):
                with urllib.request.urlopen(server.url+'/native/cas/'+snapshot,timeout=10) as response:value=json.load(response)
                return {p['project']:{k:p[k] for k in ('key','blob')} for p in value['projects']}
            assert projects(coldKey)==projects(historyKey),'Seed bundles still depend on compilation history'
            report['identicalProjectSeeds']=projects(coldKey)
            first=build('consumer-history',historyKey,True,False)
            second=build('consumer-cold',coldKey,True,False)
            for result in (first,second):
                assert result['remoteBuildHits']==1 and result['buildActions']==0 and result['compiles']==0
                assert result['managedHashes']==cold['managedHashes'] and result['testActions']==1
            assert first['actionCache']['hitKeys']==second['actionCache']['hitKeys']
            report['identicalActionKeys']=first['actionCache']['hitKeys']
            # The primary test succeeds; only the optional follow-up build fails.
            wrapper=output/'fail-primer';wrapper.write_text('#!/bin/sh\ncase " $* " in *" build //:build "*) exit 42;; esac\nexec '+shlex.quote(str(BAZEL))+' "$@"\n');wrapper.chmod(0o755)
            failedPrime=build('prime-failure',bazel=wrapper)
            assert failedPrime['accepted'] and not failedPrime['cachePrime']['accepted']
            assert failedPrime['actionCache']['stagedObjects']>0 and failedPrime['actionCache']['publishedObjects']==0
            assert failedPrime['managedHashes']==original['managedHashes'] and failedPrime['test']['passed']
            report['accepted']=True
            server.capture('final')
    finally:save()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('output','cache-binary','packages','checkout','bazel-install-cache','bazel-repository-cache'):parser.add_argument('--'+name,type=Path,required=True)
    run(parser.parse_args())
