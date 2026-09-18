"""Phase-focused native workflow comparison; retained-controller profile only."""
import argparse
import sys,json,statistics,subprocess,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools'))
from native_workflow import Workflow,BAZEL,ROOT
from probe_native_workflow import fixture,TESTS
from probe_serilog_tests import PROJECT
from protected_store import ProtectedStore
parser=argparse.ArgumentParser(description=__doc__)
for key in ('source','packages','output'): parser.add_argument('--'+key,type=Path,required=True)
parser.add_argument('--profile',choices=('retained','cli'),default='retained')
args=parser.parse_args()
out=args.output.resolve();out.mkdir()
s=fixture(args.source,args.packages,out/'s')
w=Workflow(s,out/'state',PROJECT,tests=TESTS,reuse=True,protected_store=ProtectedStore(),incremental_sources=True) if args.profile=='retained' else None
(out/'tests.json').write_text(json.dumps(TESTS))
report={'accepted':False,'profile':args.profile,'samples':[]}
try:
 for label in ['cold','seeded']+[f'unchanged-{i}' for i in range(3)]+[f'body-{i}' for i in range(3)]:
  if label.startswith('body'):
   p=s/'src/Serilog/Log.cs';p.write_text(p.read_text().replace('public static class Log\n{','public static class Log\n{\n    static int StepProbe'+label[-1]+'() => 42;'))
  if w is not None: r=w.run(out/label,operation='test',force_tests=True)
  else:
   start=time.perf_counter()
   result=subprocess.run([sys.executable,str(ROOT/'tools/native_workflow.py'),'--workspace',str(s),'--state',str(out/'state'),'--entry',PROJECT,'--tests',str(out/'tests.json'),'--reuse','--operation','test','--force-tests','--output',str(out/label)],capture_output=True,text=True)
   elapsed=time.perf_counter()-start
   (out/(label+'.log')).write_text(result.stdout+result.stderr)
   assert result.returncode==0,label
   r=json.loads((out/label/'report.json').read_text());r['seconds']=elapsed
  assert r['compiles']==(2 if label=='cold' or label.startswith('body') else 0),r['compiles']
  assert r['testActions']==1 and r['test']['total']==1 and r['test']['passed'] and r['test']['skipped']==0
  report['samples'].append(dict(label=label,seconds=r['seconds'],phases=r['phases'],preparation=r['preparation']))
  print(label,round(r['seconds'],3),r['phases'],flush=True)
 report['accepted']=True
 report['medians']={case:{key:statistics.median(r['seconds'] if key=='seconds' else r['phases'][key] for r in report['samples'] if r['label'].startswith(case)) for key in ['seconds','prepare','stage','leaseExit']} for case in ['unchanged','body']}
finally:
 (out/'report.json').write_text(json.dumps(report,indent=2))
 subprocess.run([str(BAZEL),'--nohome_rc','--noworkspace_rc','--output_base='+str(out/'state/b'),'--output_user_root='+str(out/'state/u'),'shutdown'],cwd=out/'state/g',check=True)
