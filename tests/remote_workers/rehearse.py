"""Real bazel-remote acceptance rehearsal on one host; not two-worker proof."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from cache_service import CacheService,PIN
from workload import fixture,mutate,native,remove,shutdown


def run(args):
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    report=dict(accepted=False,independentMachines=False,service=PIN,cases=[])
    def save():(output/'report.json').write_text(json.dumps(report,indent=2))
    try:
        with CacheService(args.cache_binary,output/'server') as service:
            for kind in ('diamond','serilog'):
                root=output/kind;root.mkdir();producer=root/'producer'
                command=[sys.executable,str(Path(__file__).with_name('worker.py')),'produce','--kind',kind,'--output',str(producer),
                         '--packages',str(args.packages),'--checkout',str(args.checkout),'--endpoint',service.url+'/native']
                result=subprocess.run(command,capture_output=True,text=True,timeout=900)
                (root/'producer.log').write_text(result.stdout+result.stderr);assert result.returncode==0,result.stderr
                handoff=producer/'handoff.json'
                key=json.loads(handoff.read_text())['snapshot']
                consumer=root/'consumer';command[2]='consume';command[command.index('--output')+1]=str(consumer)
                result=subprocess.run(command+['--handoff',str(handoff),'--allow-same-host'],capture_output=True,text=True,timeout=900)
                (root/'consumer.log').write_text(result.stdout+result.stderr);assert result.returncode==0,result.stderr
                report['cases'].append(json.loads((consumer/'evidence.json').read_text()));save();print(kind,'recovery passed',flush=True)
                if kind=='serilog':
                    base=root/'failed-test';source=fixture(base,kind,args.packages,args.checkout);mutate(source,kind,'failed-test')
                    try:
                        value=native(base,source,kind,args.packages,service.url+'/native',key,failed=True)
                        assert value['remote']['transport']['putRequests']==0 and not (base/'state/cache').exists()
                        report['cases'].append(dict(case='failed-test',result=value));save()
                    finally:shutdown(base)
            service.capture('final');report['accepted']=True
    finally:save()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('output','cache-binary','packages','checkout'):parser.add_argument('--'+key,type=Path,required=True)
    run(parser.parse_args())
