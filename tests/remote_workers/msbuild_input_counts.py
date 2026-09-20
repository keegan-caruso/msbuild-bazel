"""Count repeated declared package payloads and dependency composition copies."""
import argparse
import json,collections,zipfile
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
for name in ['execroot','request','output','plans']:parser.add_argument('--'+name,type=Path,required=True)
a=parser.parse_args()
root=a.execroot;r=json.loads(a.request.read_text());dirs={v['package']:root/v['source'] for v in r['packageDirectories']};counts=collections.Counter()
plans=list(a.plans.glob('project_*.plan/payload.json'))
for p in plans:
 for name in json.loads(p.read_text()):
  if name.startswith('.nuget/packages/'):counts[name]+=1
sizes={}
for name in counts:
 parts=name.split('/',4);key='/'.join(parts[2:4]);p=dirs[key]/parts[4]
 if p.is_file():sizes[name]=p.stat().st_size
 else:
  with zipfile.ZipFile(dirs[key]/(parts[2]+'.'+parts[3]+'.nupkg')) as z:sizes[name]=z.getinfo(parts[4]).file_size
m=json.loads((root/r['manifest']).read_text())['projects'];bundles={};restores=0;composes=0
for b in r['prebuilt']:
 p=root/b;x=json.loads((p/'results.json').read_text());art=json.loads((p/'artifacts.json').read_text());bundles[x['project']]=(x,art);restores+=len(art)
for project,(x,art) in bundles.items():
 seen=set()
 def visit(p):
  if p in seen:return
  seen.add(p)
  for d in m[p]['dependencies']:visit(d)
 visit(project);seen.remove(project)
 paths={a['path'] for a in art};base=str(Path(project).parent/'bin/Release'/x.get('targetFramework','net10.0'))
 for d in seen:
  for ext in ['.dll','.pdb','.xml']:
   if base+'/'+Path(d).stem+ext in paths:composes+=1
out=dict(projectPlans=len(plans),uniquePackageFiles=len(counts),packageFileAppearances=sum(counts.values()),uniquePackageBytes=sum(sizes.values()),cumulativePackageBytes=sum(sizes[k]*n for k,n in counts.items()),entryDependencyArtifactsRestored=restores,entryDependencyRuntimeCopies=composes,scope='Declared package payload appearances and code-derived copy counts, not physical IO measurements')
a.output.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
