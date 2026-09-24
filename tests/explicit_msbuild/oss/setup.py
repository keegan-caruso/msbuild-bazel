"""Restore raw controls and inventory pinned OSS sources outside build timing."""
import json,os,re,shutil,subprocess
from pathlib import Path
import argparse
parser=argparse.ArgumentParser(description="Prepare pinned source controls and evaluated benchmark fixtures.")
parser.add_argument('sources',type=Path)
parser.add_argument('output',type=Path)
parser.add_argument('--only')
args=parser.parse_args()
rules=Path(__file__).resolve().parents[3]; base=args.output.resolve(); base.mkdir(parents=True,exist_ok=True); sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']); configs=json.loads((rules/'tests/explicit_msbuild/oss/projects.json').read_text())
probe=base/'probe';probe.mkdir(exist_ok=True)
shutil.copyfile(rules/'tests/explicit_msbuild/oss/Inventory.cs.txt',probe/'Program.cs');shutil.copyfile(rules/'tests/explicit_msbuild/oss/Inventory.csproj.txt',probe/'Inventory.csproj')
subprocess.run([sdk/'dotnet','build',probe/'Inventory.csproj','-c','Release'],check=True)
for name,config in configs.items():
 if args.only and name!=args.only:continue
 checkout=args.sources.resolve()/name
 actual=subprocess.check_output(['git','-c','safe.directory='+str(checkout),'-C',str(checkout),'rev-parse','HEAD'],text=True).strip()
 assert actual==config['commit'],(name,actual,config['commit'])
 assert not subprocess.check_output(['git','-c','safe.directory='+str(checkout),'-C',str(checkout),'status','--porcelain'],text=True).strip(),'Source checkout must be clean'
 dest=base/name;dest.mkdir(exist_ok=True); source=dest/'source'
 if not source.exists():shutil.copytree(checkout,source,ignore=shutil.ignore_patterns('.git','bin','obj'))
 for patch in config.get('patches',[]):
  path=source/patch['path'];text=path.read_text(encoding='utf-8-sig')
  if patch['before'] in text:
   assert text.count(patch['before'])==1;path.write_text(text.replace(patch['before'],patch['after']))
  else:assert patch['after'] in text
 selections=[]
 for path in (source/'src').rglob('*.csproj'):
  text=path.read_text(encoding='utf-8-sig');old=re.findall(r'<TargetFrameworks>([^<]*)</TargetFrameworks>',text)
  if old:
   path.write_text(re.sub(r'<TargetFrameworks>[^<]*</TargetFrameworks>','<TargetFrameworks>'+config['framework']+'</TargetFrameworks>',text))
   selections.append(dict(project=path.relative_to(source).as_posix(),previous=re.findall(r'<TargetFrameworks>([^<]*)</TargetFrameworks>',(checkout/path.relative_to(source)).read_text(encoding='utf-8-sig')),selected=config['framework']))
 (dest/'framework-selection.json').write_text(json.dumps(selections,indent=2))
 config['properties'].update({'DebugType':'portable','ProduceReferenceAssembly':'true','NuGetAudit':'false'})
 (dest/'config.json').write_text(json.dumps(config,indent=2))
 globaljson=source/'global.json';data=json.loads(globaljson.read_text());data['sdk']={'version':'10.0.400','rollForward':'disable'};globaljson.write_text(json.dumps(data,indent=2))
 (source/'Benchmark.slnx').write_text('<Solution>'+''.join('<Project Path="'+e+'" />' for e in config['entries'])+'</Solution>')
 props=['-p:'+k+'='+v for k,v in config['properties'].items()]+['-p:RestorePackagesPath=/tmp/nuget']
 with (dest/'restore.log').open('w') as log:
  p=subprocess.run([sdk/'dotnet','restore','Benchmark.slnx',*props],cwd=source,stdout=log,stderr=subprocess.STDOUT)
 print(name,'restore',p.returncode,flush=True)
 p.check_returncode()
 # Install the selected framework packs from restored, versioned NuGet archives
 # before Bazel declares its SDK inputs. Acquisition is outside build timings.
 installed=[]
 for assets_path in source.rglob('project.assets.json'):
  assets=json.loads(assets_path.read_text())
  for framework in assets['project']['frameworks'].values():
   for download in framework.get('downloadDependencies',[]):
    pack_id=download['name']
    if pack_id not in ('Microsoft.NETCore.App.Ref','Microsoft.AspNetCore.App.Ref'):continue
    bounds=[v.strip() for v in download['version'].strip('[]').split(',')]
    assert download['version'].startswith('[') and download['version'].endswith(']') and len(set(bounds))==1,download
    version=bounds[0]
    pack=Path('/tmp/nuget')/pack_id.lower()/version
    target=sdk/'packs'/pack_id/version
    if not target.exists():shutil.copytree(pack,target)
    archive=pack/(pack_id.lower()+'.'+version+'.nupkg')
    import hashlib
    installed.append(dict(id=pack_id,version=version,sha256=hashlib.sha256(archive.read_bytes()).hexdigest()))
 if installed:(dest/'framework-packs.json').write_text(json.dumps(installed,indent=2))
 subprocess.run([sdk/'dotnet',probe/'bin/Release/net10.0/Inventory.dll',source,dest/'config.json',dest/'inventory.json'],check=True)
 # Include every graph project so solution configuration mapping keeps all
 # dependencies in Release, rather than defaulting unlisted projects to Debug.
 inventory=json.loads((dest/'inventory.json').read_text())
 (source/'Benchmark.slnx').write_text('<Solution>'+''.join('<Project Path="'+r['project']+'" />' for r in inventory)+'</Solution>')
 with (dest/'raw-control.log').open('w') as log:
  p=subprocess.run([sdk/'dotnet','build','Benchmark.slnx','-c','Release','-m:4',*props],cwd=source,stdout=log,stderr=subprocess.STDOUT)
 print(name,'raw-control',p.returncode,flush=True)
 p.check_returncode()
