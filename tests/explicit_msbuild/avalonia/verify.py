"""Compare actual graph references, resources, XAML methods and runtime behavior."""
import hashlib,json,os,subprocess,sys
from pathlib import Path
folder=Path(sys.argv[1]).resolve();base=Path(sys.argv[2]).resolve();sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT']);rules=Path(__file__).resolve().parents[3];probe=folder/'inspect';probe.mkdir(exist_ok=True)
(probe/'Program.cs').write_text((rules/'tests/explicit_msbuild/avalonia/Inspect.cs.txt').read_text());(probe/'Inspect.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
subprocess.run([sdk/'dotnet','build',probe/'Inspect.csproj','-c','Release'],check=True,stdout=subprocess.DEVNULL)
program=probe/'bin/Release/net10.0/Inspect.dll';rows=json.loads((folder/'inventory.json').read_text());binroot=base/'execroot/_main/bazel-out';results=[];runtimes=[]
def inspect(path):return json.loads(subprocess.check_output([sdk/'dotnet',program,'inspect',path],text=True))
for row in rows:
 name=row['properties']['AssemblyName'];label=Path(row['project']).stem
 references=list(binroot.glob('*/bin/upstream/'+label+'.reference/'+name+'.dll'));assert references,name
 raw=folder/'source'/Path(row['project']).parent/'obj/Release'/row['framework']/'ref'/(name+'.dll')
 for ref in references:assert raw.read_bytes()==ref.read_bytes(),('reference mismatch',name,ref)
 runtime=list(binroot.glob('*/bin/upstream/'+label+'.runtime/'+name+'.dll'))[0];runtimes.append(runtime.parent)
 rawruntime=folder/'source'/Path(row['project']).parent/'bin/Release'/row['framework']/(name+'.dll')
 a=inspect(rawruntime);b=inspect(runtime)
 assert a['resources']==b['resources'],('resource mismatch',name)
 xaml=lambda data:sorted((t['name'],m['name']) for t in data['types'] for m in t['methods'] if '!XamlIl' in m['name'] or t['name'].startswith('CompiledAvaloniaXaml.'))
 assert xaml(a)==xaml(b),(name,'XAML method mismatch')
 results.append(dict(project=row['project'],framework=row['framework'],referenceHash=hashlib.sha256(raw.read_bytes()).hexdigest(),referenceBytesEqual=True,runtimeBytesEqual=rawruntime.read_bytes()==runtime.read_bytes(),resources=b['resources'],compiledXamlMethods=len(xaml(b))))
rawdir=folder/'source/src/Avalonia.Themes.Simple/bin/Release/net8.0'
a=json.loads(subprocess.check_output([sdk/'dotnet',program,'run',rawdir],text=True));b=json.loads(subprocess.check_output([sdk/'dotnet',program,'run',*runtimes],text=True));assert a==b,(a,b);assert b['count']==int(sys.argv[3]) if len(sys.argv)>3 else b['count']==1
assert next(r for r in results if r['project'].endswith('/Avalonia.Themes.Simple.csproj'))['compiledXamlMethods']>0,results
report=dict(projects=results,runtime=b);(folder/'parity.json').write_text(json.dumps(report,indent=2)+'\n');print('Verified',len(results),'reference assemblies, resources, compiled XAML methods, and runtime',b,flush=True)
