"""Prepare a pinned Avalonia graph (Simple theme by default); setup is outside build timing."""
import argparse,json,os,shutil,subprocess,sys,time
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('checkout',type=Path);p.add_argument('destination',type=Path);p.add_argument('--entry',action='append');a=p.parse_args()
rules=Path(__file__).resolve().parents[3];checkout=a.checkout.resolve();dest=a.destination.resolve();dest.mkdir(parents=True);source=dest/'source';sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
assert subprocess.check_output(['git','-C',checkout,'rev-parse','HEAD'],text=True).strip()=='37fbd9655cc581ff5b1c6b1fb1be4e3118c889d0'
subprocess.run(['git','-C',checkout,'diff','--exit-code','HEAD'],check=True,stdout=subprocess.DEVNULL)
data_grid=checkout/'external/Avalonia.Controls.DataGrid'
if (data_grid/'.git').exists():
 assert subprocess.check_output(['git','-C',data_grid,'rev-parse','HEAD'],text=True).strip()=='85a0b32ef6d963c1d67619ca3e2f6da0bc43ac9a'
 subprocess.run(['git','-C',data_grid,'diff','--exit-code','HEAD'],check=True,stdout=subprocess.DEVNULL)
shutil.copytree(checkout,source,ignore=shutil.ignore_patterns('.git','bin','obj','artifacts','._*'))
globaljson=source/'global.json';data=json.loads(globaljson.read_text());data['sdk']={'version':'10.0.400','rollForward':'disable'};globaljson.write_text(json.dumps(data))
config={'sourceSubdir':'upstream','itemMetadata':['DBusGeneratorMode'],'framework':'net8.0','entries':a.entry or ['src/Avalonia.Themes.Simple/Avalonia.Themes.Simple.csproj'],'properties':{'AvsSkipBuildingLegacyTargetFrameworks':'True','DebugType':'portable','ProduceReferenceAssembly':'true','NuGetAudit':'false'}}
(dest/'config.json').write_text(json.dumps(config,indent=2))
props=['-p:'+k+'='+v for k,v in config['properties'].items()]+['-p:RestorePackagesPath='+str(dest/'nuget')]
for index, entry in enumerate(config['entries']):
 entry=source/entry
 for name,args in [('restore',['restore',entry]),('raw-cold',['build',entry,'-f','net8.0','-c','Release','--no-restore','-m:4'])]:
  start=time.perf_counter()
  with (dest/(name+('' if index==0 else '-'+str(index))+'.log')).open('w') as log:r=subprocess.run([sdk/'dotnet',*args,*props],cwd=source,stdout=log,stderr=subprocess.STDOUT)
  print(name,entry.name,r.returncode,round(time.perf_counter()-start,3),flush=True);r.check_returncode()
probe=dest/'probe';probe.mkdir();shutil.copyfile(rules/'tests/explicit_msbuild/oss/Inventory.csproj.txt',probe/'Inventory.csproj')
code=(rules/'tests/explicit_msbuild/oss/Inventory.cs.txt').read_text().replace('"EditorConfigFiles"','"EditorConfigFiles","AvaloniaResource","AvaloniaXaml"')
(probe/'Program.cs').write_text(code)
subprocess.run([sdk/'dotnet','build',probe/'Inventory.csproj','-c','Release'],check=True)
subprocess.run([sdk/'dotnet',probe/'bin/Release/net10.0/Inventory.dll',source,dest/'config.json',dest/'inventory.json'],check=True)

rows=json.loads((dest/'inventory.json').read_text())
config['toolBindings']={r['project']:{'AvaloniaBuildTasksLocation':'src/Avalonia.Build.Tasks/Avalonia.Build.Tasks.csproj'} for r in rows if 'build/BuildTargets.targets' in r['imports']}
(dest/'config.json').write_text(json.dumps(config,indent=2))
subprocess.run([sys.executable,rules/'tests/explicit_msbuild/oss/prepare.py',dest,rules],check=True)

from desktop_inputs import configure
configure(dest)
