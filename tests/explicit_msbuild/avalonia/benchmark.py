"""Paired warm no-op and observable XAML edits after setup and an initial build."""
import json,os,subprocess
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from benchmarks.measure import command as timed_command
folder=Path(sys.argv[1]).resolve();base=Path(sys.argv[2]).resolve();sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);bazel=os.environ['RULES_MSBUILD_BAZEL'];rules=Path(__file__).resolve().parents[3];config=json.loads((folder/'config.json').read_text());workspace=folder/'bazel';source=folder/'source';rows=[]
props=['-p:'+k+'='+v for k,v in config['properties'].items()]+['-p:RestorePackagesPath='+str(folder/'nuget')]
raw=[sdk/'dotnet','build',config['entries'][0],'-f','net8.0','-c','Release','--no-restore','-m:4',*props]
startup=[bazel,'--output_base='+str(base),'--ignore_all_rc_files'];flags=['--remote_download_outputs=all','--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE'],'--disk_cache='+str(folder/'cache'),'--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=4','--jobs=4']
def run(name,args,cwd):
 p,elapsed=timed_command(args,cwd,folder/(name+'.log'))
 assert p.returncode==0,name;rows.append(dict(case=name,seconds=elapsed));print(name,round(elapsed,3),flush=True)
def bz(name):run(name,startup+['build','//upstream:benchmark','--execution_log_json_file='+str(folder/(name+'.execution.json'))]+flags,workspace)
for i in range(3):run('raw-noop-'+str(i),raw,source);bz('bazel-noop-'+str(i))
relative='src/Avalonia.Themes.Simple/SimpleTheme.xaml';original=(source/relative).read_text();opacity=sys.argv[3] if len(sys.argv)>3 else '0.75';changed=original.replace('</Styles>',f'<Style Selector="Button"><Setter Property="Opacity" Value="{opacity}" /></Style></Styles>')
for root in [source,workspace/'upstream']:(root/relative).write_text(changed)
run('raw-xaml-edit',raw,source);bz('bazel-xaml-edit')
text=(folder/'bazel-xaml-edit.execution.json').read_text();decoder=json.JSONDecoder();executed=[]
while text.strip():
 action,end=decoder.raw_decode(text.lstrip());text=text.lstrip()[end:]
 if action.get('mnemonic')=='MSBuildAssembly' and not action.get('cacheHit'):executed.append(action)
assert len(executed)==1, 'Use a new opacity value to measure an uncached XAML edit'
subprocess.run([sys.executable,rules/'tests/explicit_msbuild/avalonia/verify.py',folder,base,'2'],check=True)
(folder/'xaml-edit-parity.json').write_bytes((folder/'parity.json').read_bytes())
for root in [source,workspace/'upstream']:(root/relative).write_text(original)
run('raw-xaml-revert',raw,source);bz('bazel-xaml-revert')
(folder/'benchmark.json').write_text(json.dumps(rows,indent=2)+'\n')
subprocess.run([sys.executable,rules/'tests/explicit_msbuild/avalonia/verify.py',folder,base,'1'],check=True)
(folder/'benchmark.json').write_text(json.dumps(rows,indent=2)+'\n')
subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
