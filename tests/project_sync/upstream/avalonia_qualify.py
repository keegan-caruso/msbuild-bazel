"""Run the full generated Avalonia slice and compare raw tests and assembly shape."""
import argparse
from collections import Counter
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.path = [p for p in sys.path if Path(p).resolve() != Path(__file__).resolve().parent]
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'explicit_msbuild/avalonia'))
from suite_support import outcomes, serialize

p=argparse.ArgumentParser(description=__doc__)
for key in ['prepared','workspace','base','output']:p.add_argument(key,type=Path)
p.add_argument('--cache',required=True)
a=p.parse_args();prepared,w,base,out=[v.resolve() for v in [a.prepared,a.workspace,a.base,a.output]]
out.mkdir(parents=True,exist_ok=False)
rows=json.loads((prepared/'inventory.json').read_text());roots=[r for r in rows if r['entry']]
test_inputs=json.loads((prepared/'test-inputs.json').read_text())
sdk=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
cmd=[os.environ['RULES_MSBUILD_BAZEL'],'--output_base='+str(base),'--host_jvm_args=-Xmx768m','--ignore_all_rc_files']
labels={r['id']:'upstream_'+r['project'].removesuffix('.csproj').replace('/','_')+'_'+r['framework'].replace('.','_') for r in rows}
expected={}
for row in roots:
    if not row['project'].startswith('tests/'):continue
    suite=row['properties']['AssemblyName'];raw=prepared/'source'/Path(row['project']).parent/'bin/Release'/row['framework']/(suite+'.dll')
    resultdir=out/('raw-'+suite)
    with (out/('raw-'+suite+'.log')).open('w') as log:
        result=subprocess.run([sdk/'dotnet',test_inputs['runner'],raw,'/Logger:trx;LogFileName=results.trx','/ResultsDirectory:'+str(resultdir)],cwd=prepared/'source/tests',env=dict(os.environ,DOTNET_ROLL_FORWARD='Major',**(test_inputs['environment'] if suite.startswith('Avalonia.Skia.') else {})),stdout=log,stderr=subprocess.STDOUT)
    expected[suite]=outcomes(resultdir/'results.trx')
    assert result.returncode==0,(suite,result.returncode)
    print('raw',suite,dict(Counter({k:sum(n for (_,o),n in expected[suite].items() if o==k) for k in ['Passed','NotExecuted','Failed']})),flush=True)
try:
    execution=out/'build.execution.json'
    with (out/'build.log').open('w') as log:
        began=time.monotonic()
        result=subprocess.run(cmd+['test',*['//:'+labels[r['id']] for r in roots],'--jobs=2','--worker_max_instances=2','--remote_cache='+a.cache,'--remote_download_outputs=all','--test_output=errors','--execution_log_json_file='+str(execution)],cwd=w,stdout=log,stderr=subprocess.STDOUT)
    assert result.returncode==0,out/'build.log'
    elapsed=time.monotonic()-began
    for row in roots:
        suite=row['properties']['AssemblyName']
        if suite not in expected:continue
        actual=outcomes(w/'bazel-testlogs'/labels[row['id']]/'test.outputs/results.trx')
        assert actual==expected[suite],(suite,serialize(expected[suite]-actual),serialize(actual-expected[suite]))
    probe=out/'inspect';probe.mkdir()
    shutil.copyfile(Path(__file__).resolve().parents[2]/'explicit_msbuild/avalonia/Inspect.cs.txt',probe/'Program.cs')
    (probe/'Inspect.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><ImplicitUsings>enable</ImplicitUsings><Nullable>enable</Nullable></PropertyGroup></Project>')
    subprocess.run([sdk/'dotnet','build',probe/'Inspect.csproj','-c','Release'],check=True,stdout=subprocess.DEVNULL)
    def inspect(path):return json.loads(subprocess.check_output([sdk/'dotnet',probe/'bin/Release/net10.0/Inspect.dll','inspect',path],text=True))
    def xaml(data):return sorted((t['name'],m['name']) for t in data['types'] for m in t['methods'] if '!XamlIl' in m['name'] or t['name'].startswith('CompiledAvaloniaXaml.'))
    def com_shape(data):
        # Existing Desktop qualification boundary: Roslyn file-local COM types
        # encode their source path in these private names. Do not normalize any
        # public type, member signature, attribute, resource or other assembly.
        count=0
        for item in data['types']:
            if item['name'].startswith('.<Avalonia_Win32_Automation_'):
                name,n=re.subn(r'(?<=>)F[0-9A-F]{64}(?=__(?:ComClassInformation|InterfaceInformation|InterfaceImplementation)$)','F<PATH_HASH>',item['name'])
                if n:
                    assert item['attributes'] & 7 == 0
                    item['name']=name;count+=n
        assert count==53,count
        return data
    comparisons=[];binroot=base/'execroot/_main/bazel-out'
    for row in rows:
        name=row['properties']['AssemblyName'];label=labels[row['id']];raw=prepared/'source'/Path(row['project']).parent
        reference=raw/'obj/Release'/row['framework']/'ref'/(name+'.dll')
        refs=list(binroot.glob('*/bin/'+label+'.reference/'+name+'.dll'));assert refs,label
        com = row['project']=='src/Windows/Avalonia.Win32.Automation/Avalonia.Win32.Automation.csproj'
        for actual in refs:
            if com:assert com_shape(inspect(actual))==com_shape(inspect(reference)),('COM metadata mismatch',label)
            else:assert actual.read_bytes()==reference.read_bytes(),('reference mismatch',label,actual)
        rawdata=inspect(raw/'bin/Release'/row['framework']/(name+'.dll'))
        runtimes=list(binroot.glob('*/bin/'+label+'.runtime/'+name+'.dll'));assert runtimes,label
        for runtime in runtimes:
            data=inspect(runtime)
            assert rawdata['resources']==data['resources'],('resources',label)
            assert xaml(rawdata)==xaml(data),('XAML',label)
        comparisons.append(dict(referenceBytesEqual=not com,normalizedPrivateComTypes=53 if com else 0,label=label,referenceConfigurations=len(refs),referenceSha256=hashlib.sha256(reference.read_bytes()).hexdigest(),resources=len(rawdata['resources']),xamlMethods=len(xaml(rawdata))))
    for generated in json.loads((prepared/'expanded-generators.json').read_text()):
        actual=w/'bazel-bin'/(generated['label']+'.generated')/generated['filename']
        assert actual.read_bytes()==(prepared/'source'/generated['output']).read_bytes()
    text=execution.read_text();decoder=json.JSONDecoder();offset=0;actions=[]
    while offset<len(text):
        if text[offset].isspace():offset+=1;continue
        row,offset=decoder.raw_decode(text,offset);actions.append({k:row.get(k) for k in ['mnemonic','targetLabel','cacheHit','runner']})
    (out/'results.json').write_text(json.dumps(dict(targets=['//:'+labels[r['id']] for r in roots],testTargets={r['properties']['AssemblyName']:'//:'+labels[r['id']] for r in roots if r['project'].startswith('tests/')},configuredNodes=len(rows),projectPaths=len({r['project'] for r in rows}),entries=len(roots),seconds=elapsed,actions=actions,assemblies=comparisons,outcomes={s:serialize(v) for s,v in expected.items()},rawParity=True),indent=2)+'\n')
    subprocess.run(cmd+['run','//:sync','--','--check'],cwd=w,check=True)
finally:
    subprocess.run(cmd+['shutdown'],cwd=w,check=True)
