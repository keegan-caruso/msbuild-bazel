"""Run one reproducible HTTP cache case. Producer and consumer use separate containers."""
import argparse,hashlib,json,os,re,subprocess,time
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('workspace',type=Path);p.add_argument('base',type=Path);p.add_argument('report',type=Path);p.add_argument('case',choices=['baseline','tool','idl','xaml']);p.add_argument('--cache',required=True);p.add_argument('--upload',action='store_true');p.add_argument('--expect-hits',action='store_true');args=p.parse_args();workspace=args.workspace.resolve();base=args.base.resolve();report=args.report.resolve();report.parent.mkdir(parents=True,exist_ok=True)
originals=json.loads((workspace/'remote-originals.json').read_text())
for kind,item in originals.items():
 text=item['text']
 if args.case==kind:
  if kind=='tool':
   old='public bool Execute()\n        {';assert text.count(old)==1;text=text.replace(old,old+'\n            BuildEngine.LogMessage("CACHE_TOOL_IMPLEMENTATION_EDIT", MessageImportance.High);')
  elif kind=='xaml':text=text.replace('</Styles>','<Style Selector="Button"><Setter Property="Opacity" Value="0.72" /></Style></Styles>')
  else:assert text.count('AvnKeyNone = 0')==1;text=text.replace('AvnKeyNone = 0','AvnKeyNone = 42')
 (workspace/'upstream'/item['path']).write_text(text)
startup=[os.environ['RULES_MSBUILD_BAZEL'],'--output_base='+str(base),'--output_user_root='+str(base.parent/(base.name+'-user')),'--ignore_all_rc_files']
command=startup+['build','//upstream:cache_benchmark','--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE'],'--disk_cache=','--remote_cache='+args.cache,'--remote_upload_local_results='+str(args.upload).lower(),'--remote_download_outputs=all','--strategy=MSBuildAssembly=worker','--strategy=MSBuildGenerate=worker','--worker_max_instances=MSBuildAssembly=4','--worker_max_instances=MSBuildGenerate=1','--jobs=4','--execution_log_json_file='+str(report.with_suffix('.execution.json'))]
start=time.perf_counter()
with report.with_suffix('.log').open('w') as log:result=subprocess.run(command,cwd=workspace,stdout=log,stderr=subprocess.STDOUT)
seconds=time.perf_counter()-start
try:
 assert result.returncode==0,report.with_suffix('.log')
 text=report.with_suffix('.execution.json').read_text();decoder=json.JSONDecoder();actions=[]
 while text.strip():
  action,end=decoder.raw_decode(text.lstrip());text=text.lstrip()[end:]
  if action.get('mnemonic') in ('MSBuildAssembly','MSBuildGenerate'):actions.append(action)
 executed=[a for a in actions if not a.get('cacheHit')];cached=[a for a in actions if a.get('cacheHit')]
 if args.expect_hits:assert len(actions)==13 and not executed,(len(actions),[(a.get('targetLabel'),a.get('runner')) for a in executed])
 elif not args.upload:
  labels=[a.get('targetLabel') for a in executed]
  if args.case=='xaml':assert labels==['//upstream:Avalonia.Themes.Simple'],labels
  elif args.case=='idl':assert labels==['//upstream:cache_idl'],labels
  elif args.case=='tool':assert '//upstream:Avalonia.Build.Tasks' in labels and '//upstream:Avalonia.Themes.Simple' in labels,labels;assert 'CACHE_TOOL_IMPLEMENTATION_EDIT' in report.with_suffix('.log').read_text()
 hashes={};binroot=base/'execroot/_main/bazel-out'
 for path in sorted(binroot.glob('*/bin/upstream/*')):
  if path.is_dir() and path.name.endswith(('.runtime','.reference','.generated')):
   for file in sorted(path.rglob('*')):
    if file.is_file() and not file.name.endswith('.params'):hashes[file.relative_to(binroot).as_posix()]=hashlib.sha256(file.read_bytes()).hexdigest()
 if args.case=='idl':
  generated=next(binroot.glob('*/bin/upstream/cache_idl.generated/Interop.Generated.cs')).read_text();assert re.search(r'AvnKeyNone\s*=\s*42',generated)
 data=dict(case=args.case,seconds=seconds,executed=[a.get('targetLabel') for a in executed],cacheHits=len(cached),actions=len(actions),hashes=hashes,workspace=str(workspace),diskCache=False,upload=args.upload)
 report.write_text(json.dumps(data,indent=2)+'\n');print({k:v for k,v in data.items() if k!='hashes'},flush=True)
finally:subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
