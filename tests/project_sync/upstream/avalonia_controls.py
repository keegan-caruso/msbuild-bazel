"""Edit/revert controls for the complete generated Avalonia qualification slice."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

w, base, baseline, out = [Path(p).resolve() for p in sys.argv[1:5]]
cache = sys.argv[5]
out.mkdir(parents=True, exist_ok=False)
saved = json.loads(baseline.read_text())
cmd = [os.environ['RULES_MSBUILD_BAZEL'], '--output_base='+str(base), '--host_jvm_args=-Xmx768m', '--ignore_all_rc_files']
flags = ['--jobs=2', '--worker_max_instances=2', '--remote_cache='+cache, '--remote_upload_local_results=false', '--remote_download_outputs=all', '--disk_cache=', '--test_output=errors']
source = w/'upstream/src/Avalonia.Remote.Protocol/AvaloniaRemoteMessageGuidAttribute.cs'
resource = w/'upstream/src/Avalonia.Themes.Simple/Controls/Button.xaml'
idl = w/'upstream/src/Avalonia.Native/avn.idl'
originals = {p:p.read_bytes() for p in [source, resource, idl]}
records = []
ns = {'t':'http://microsoft.com/schemas/VisualStudio/TeamTest/2010'}
def parity():
    for suite, label in saved['testTargets'].items():
        path = w/'bazel-testlogs'/label.split(':')[1]/'test.outputs/results.trx'
        actual = Counter((r.get('testName'),r.get('outcome')) for r in ET.parse(path).findall('.//t:UnitTestResult', ns))
        assert actual == Counter({(name,outcome):count for name,outcome,count in saved['outcomes'][suite]}),suite

def run(case, required=(), exact=True, reference=None, changed=False, output=None):
    before = hashlib.sha256(output.read_bytes()).hexdigest() if output else None
    execution = out/(case+'.execution.json')
    began = time.monotonic()
    with (out/(case+'.log')).open('w') as log:
        result = subprocess.run(cmd+['test', *saved['targets'], *flags, '--execution_log_json_file='+str(execution)],cwd=w,stdout=log,stderr=subprocess.STDOUT)
    assert result.returncode==0,case
    text=execution.read_text();decoder=json.JSONDecoder();offset=0;actions=[]
    while offset<len(text):
        if text[offset].isspace():offset+=1;continue
        row,offset=decoder.raw_decode(text,offset)
        if not row.get('cacheHit') and row.get('mnemonic') in ['MSBuildAssembly','MSBuildGenerate','TestRunner']:
            actions.append((row['mnemonic'],row['targetLabel']))
    builds=set(row for row in actions if row[0]!='TestRunner')
    assert builds==set(required) if exact else set(required)<=builds,(case,builds,required)
    if reference:assert (reference.read_bytes()!=refs[reference])==changed,case
    if output:assert hashlib.sha256(output.read_bytes()).hexdigest()!=before,case
    parity()
    records.append(dict(case=case,seconds=round(time.monotonic()-began,3),executed=actions,rawParity=True,referenceChanged=changed if reference else None))
    (out/'results.json').write_text(json.dumps(records,indent=2)+'\n')
    print(case,len(builds),'build actions',flush=True)

def label(project,framework='net8_0'):
    return '//:upstream_src_'+project+'_'+project+'_'+framework
protocol=[label('Avalonia.Remote.Protocol',f) for f in ['net8_0','netstandard2_0']]
themes=[label('Avalonia.Themes.Simple',f) for f in ['net8_0','netstandard2_0']]
reference=w/'bazel-bin'/(protocol[0].split(':')[1]+'.reference/Avalonia.Remote.Protocol.dll')
refs={reference:reference.read_bytes()}
try:
    run('baseline')
    source.write_bytes(originals[source].replace(b'Guid = Guid.Parse(guid);',b'Guid = Guid.Parse(guid);\n            GC.KeepAlive(guid);'))
    run('body',[('MSBuildAssembly',l) for l in protocol],reference=reference)
    source.write_bytes(originals[source]);run('body-reverted')
    source.write_bytes(originals[source].replace(b'public Guid Guid { get; }',b'public Guid Guid { get; }\n        public bool QualificationApi => true;'))
    run('api',[('MSBuildAssembly',l) for l in protocol],exact=False,reference=reference,changed=True)
    assert len([r for r in records[-1]['executed'] if r[0]=='MSBuildAssembly'])>len(protocol)
    source.write_bytes(originals[source]);run('api-reverted')
    resource.write_bytes(originals[resource].replace(b'  <ControlTheme ',b'  <Color x:Key="GeneratedGraphMarker">#010203</Color>\n  <ControlTheme ',1))
    run('xaml',[('MSBuildAssembly',l) for l in themes],output=w/'bazel-bin'/(themes[0].split(':')[1]+'.runtime/Avalonia.Themes.Simple.dll'))
    resource.write_bytes(originals[resource]);run('xaml-reverted')
    assert originals[idl].count(b'AvnKeyNone = 0,')==1
    idl.write_bytes(originals[idl].replace(b'AvnKeyNone = 0,',b'AvnKeyNone = -7742,'))
    run('idl',[('MSBuildGenerate','//:desktop_idl_4'),('MSBuildAssembly',label('Avalonia.Native')),('MSBuildAssembly',label('Avalonia.Desktop'))],output=w/'bazel-bin/desktop_idl_4.generated/Interop.Generated.cs')
    idl.write_bytes(originals[idl]);run('idl-reverted')
    generated=(w/'projects.generated.bzl').read_bytes()
    source.unlink()
    p=subprocess.run(cmd+['run','//:sync','--','--check'],cwd=w,text=True,capture_output=True)
    (out/'missing-source.log').write_text(p.stdout+p.stderr)
    assert p.returncode and (w/'projects.generated.bzl').read_bytes()==generated
    source.write_bytes(originals[source])
    subprocess.run(cmd+['run','//:sync','--','--check'],cwd=w,check=True,stdout=subprocess.DEVNULL)
finally:
    for path,data in originals.items():path.write_bytes(data)
    subprocess.run(cmd+['shutdown'],cwd=w,check=True)
