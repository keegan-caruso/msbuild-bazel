"""Extra test protocol controls; run after protocol.py, vstest.py, and cache setup."""
import json,os,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1]).resolve();workspace=root/'src';bazel=os.environ['RULES_MSBUILD_BAZEL']
startup=[bazel,'--host_jvm_args=-Xmx768m','--output_base='+str(root/'base'),'--ignore_all_rc_files'];rows=[]
def run(name,target,flags,success):
 p=subprocess.run(startup+['test',target,'--test_output=all','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--build_event_json_file='+str(root/(name+'.bep')),*flags],cwd=workspace,capture_output=True,text=True)
 (root/(name+'.log')).write_text(p.stdout+p.stderr);assert (p.returncode==0)==success,(name,(p.stdout+p.stderr)[-2000:])
 events=[json.loads(l) for l in (root/(name+'.bep')).read_text().splitlines()];metrics=next(e['buildMetrics']['actionSummary'] for e in events if 'buildMetrics' in e);counts={r['mnemonic']:int(r.get('actionsExecuted',0)) for r in metrics.get('actionData',[])};rows.append(dict(case=name,exit=p.returncode,actions=counts));print(rows[-1],flush=True);return counts
try:
 run('extra-baseline','//Vstest/Xunit',[],True)
 p=workspace/'Mtp/BUILD.bazel';old=p.read_text()
 try:
  p.write_text(old.replace('size="small"','allow_empty_tests=True,env={"CASE":"pass"},size="small"'))
  run('mtp-allow-empty','//Mtp',['--test_filter=/*/*/Tests/Absent'],True)
 finally:p.write_text(old)
 p=workspace/'Vstest/BUILD.bazel';old=p.read_text()
 try:
  p.write_text(old.replace('vstest.console.dll','missing.dll'))
  counts=run('missing-runner','//Vstest/Xunit',[],False);assert counts.get('MSBuildAssembly',0)==0,counts
 finally:p.write_text(old)
 p=workspace/'Vstest/Xunit/BUILD.bazel';old=p.read_text()
 try:
  p.write_text(old.replace('path="build/net8.0"','path="missing-adapter"'))
  counts=run('missing-adapter','//Vstest/Xunit',[],False);assert counts.get('MSBuildAssembly',0)==0,counts
 finally:p.write_text(old)
 run('no-shards','//Vstest/Xunit',['--test_sharding_strategy=forced=2'],False)
 run('extra-recovered','//Vstest/Xunit',[],True)
finally:
 (root/'extra-results.json').write_text(json.dumps(rows,indent=2)+'\n')
 subprocess.run(startup+['shutdown'],cwd=workspace)
