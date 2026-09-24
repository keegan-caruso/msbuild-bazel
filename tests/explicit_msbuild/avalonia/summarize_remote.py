"""Validate saved producer/consumer reports and emit compact reviewable evidence."""
import hashlib,json,statistics,sys
from pathlib import Path
root=Path(sys.argv[1]);out=Path(sys.argv[2])
def read(name):return json.loads((root/(name+'.json')).read_text())
def digest(hashes):return hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()
seed=read('seed');baselines=[read(n) for n in ['baseline','recovery-baseline','baseline-3']]
for row in baselines:
 assert row['hashes']==seed['hashes'] and row['cacheHits']==13 and not row['executed'] and not row['diskCache'] and not row['upload']
summary=dict(platform='Ubuntu 22.04 ARM64; two Apple containers on one Mac',sdk='10.0.400',bazel='9.2.0',cache='bazel-remote 2.6.2 over HTTP',producerWorkspace=seed['workspace'],consumerWorkspace=baselines[0]['workspace'],seedSeconds=seed['seconds'],baselineSeconds=[r['seconds'] for r in baselines],baselineMedianSeconds=statistics.median(r['seconds'] for r in baselines),baselineActions=13,baselineExecuted=0,artifactCount=len(seed['hashes']),artifactDigest=digest(seed['hashes']),cases={})
for case in ['idl','xaml','tool']:
 first=read(case);published=read('seed-'+case);recovered=read('recovery-'+case)
 assert first['hashes']==published['hashes']==recovered['hashes'],case
 assert recovered['cacheHits']==13 and not recovered['executed'] and not recovered['diskCache'] and not recovered['upload'],case
 runtime=read('recovery-'+case+'-runtime');assert runtime['count']==(2 if case=='xaml' else 1),runtime
 changed=[k for k,v in first['hashes'].items() if seed['hashes'].get(k)!=v]
 if case=='tool':assert not any('.reference/' in k for k in changed)
 summary['cases'][case]=dict(firstSeconds=first['seconds'],firstExecuted=first['executed'],firstCacheHits=first['cacheHits'],independentExecutionBytesEqual=True,recoverySeconds=recovered['seconds'],recoveryActions=13,recoveryExecuted=0,recoveryBytesEqual=True,runtime=runtime,artifactDigest=digest(recovered['hashes']),changedArtifacts=changed)
summary['cacheStatus']=read('cache-status');out.write_text(json.dumps(summary,indent=2)+'\n');print('Validated baseline and all edited artifact sets; baseline median',round(summary['baselineMedianSeconds'],3),'s')
