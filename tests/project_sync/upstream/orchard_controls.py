"""Body/API/resource invalidation and repair in the complete generated CMS graph."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

w, base, seed, out = [Path(p).resolve() for p in sys.argv[1:5]]
cache = sys.argv[5]
out.mkdir(parents=True, exist_ok=False)
original_targets = {r['targetLabel'] for r in json.loads(seed.read_text())['actions'] if r['mnemonic'] == 'MSBuildAssembly'}
cmd = [os.environ['RULES_MSBUILD_BAZEL'], '--host_jvm_args=-Xmx1536m', '--output_base='+str(base), '--ignore_all_rc_files']
target = '//:src_OrchardCore.Cms.Web_OrchardCore.Cms.Web'
source = w/'src/OrchardCore/OrchardCore.Abstractions/Extensions/Manifests/NotFoundManifestInfo.cs'
resource = w/'src/OrchardCore.Modules/OrchardCore.Setup/wwwroot/Styles/setup.min.css'
original = {p:p.read_bytes() for p in [source,resource]}
core = '//:src_OrchardCore_OrchardCore.Abstractions_OrchardCore.Abstractions_net10_0'
setup = '//:src_OrchardCore.Modules_OrchardCore.Setup_OrchardCore.Setup_net10_0'
reference = w/'bazel-bin'/ (core.split(':')[1]+'.reference/OrchardCore.Abstractions.dll')
setup_reference = w/'bazel-bin'/(setup.split(':')[1]+'.reference/OrchardCore.Setup.dll')
with (out/'warmup.log').open('w') as log:
    subprocess.run(cmd+['build',target,'--jobs=2','--remote_cache='+cache,'--remote_download_outputs=all'],cwd=w,stdout=log,stderr=subprocess.STDOUT,check=True)
baseline = reference.read_bytes()
setup_baseline = setup_reference.read_bytes()
rows=[]
def run(name, producer=None, api=False, resource_edit=False):
    execution = out/(name+'.execution.json')
    with (out/(name+'.log')).open('w') as log:
        result=subprocess.run(cmd+['build',target,'--jobs=2','--worker_max_instances=2','--remote_cache='+cache,'--remote_upload_local_results=false','--disk_cache=','--remote_download_outputs=all','--execution_log_json_file='+str(execution)],cwd=w,stdout=log,stderr=subprocess.STDOUT)
    assert result.returncode == 0,name
    text=execution.read_text(); decoder=json.JSONDecoder(); offset=0; rebuilt=set()
    while offset<len(text):
        if text[offset].isspace():offset+=1;continue
        row,offset=decoder.raw_decode(text,offset)
        if row.get('mnemonic')=='MSBuildAssembly' and not row.get('cacheHit'):rebuilt.add(row['targetLabel'])
    assert (reference.read_bytes()!=baseline)==api,name
    if producer:
        assert producer in rebuilt,(name,rebuilt)
        if api:assert len(rebuilt)>1,(name,rebuilt)
        else:
            expected={producer}
            if resource_edit:
                # The module emits asset metadata into its reference assembly.
                # Preserve the same four-project invalidation as the authored graph.
                expected.update({target, '//:src_OrchardCore_OrchardCore.Application.Cms.Core.Targets_OrchardCore.Application.Cms.Core.Targets_net10_0', '//:src_OrchardCore_OrchardCore.Application.Cms.Targets_OrchardCore.Application.Cms.Targets_net10_0'})
            assert rebuilt==expected,(name,rebuilt)
    else:assert not rebuilt,(name,rebuilt)
    setup_changed = setup_reference.read_bytes()!=setup_baseline
    if not api:assert setup_changed==resource_edit,name
    smoke=Path(__file__).resolve().parents[2]/'explicit_msbuild/orchard_compatibility/smoke.py'
    subprocess.run([sys.executable,smoke,w,out,name+'-smoke','--target',target.split(':')[1]],check=True,stdout=subprocess.DEVNULL)
    result=json.loads((out/(name+'-smoke.json')).read_text())
    assert result[1]['sha256']==hashlib.sha256(resource.read_bytes()).hexdigest()
    rows.append(dict(case=name,rebuilt=sorted(rebuilt),coreReferenceChanged=api,setupReferenceChanged=setup_changed,unrebuiltAssemblies=len(original_targets-rebuilt),renderedEndpoints=4,embeddedResourceMatchesInput=True))
    (out/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(name,'rebuilt',len(rebuilt),flush=True)
def restore():
    for p,data in original.items():p.write_bytes(data)
try:
    if '--resource-only' not in sys.argv:
        text=source.read_text();needle='string Description => null;';assert needle in text
        source.write_text(text.replace(needle,'string Description => "generated-graph-control";'))
        run('body',core);restore();run('body-reverted')
        source.write_text(text.replace('public bool Exists => false;','public bool Exists => false;\n    public bool QualificationApi => true;'))
        run('api',core,api=True);restore();run('api-reverted')
    resource.write_bytes(original[resource]+b'\n/* generated resource control */\n')
    run('resource',setup,resource_edit=True);restore();run('resource-reverted')
    generated=(w/'projects.generated.bzl').read_bytes()
    source.unlink()
    result=subprocess.run(cmd+['run','//:sync','--','--check'],cwd=w,text=True,capture_output=True)
    (out/'missing-source.log').write_text(result.stdout+result.stderr)
    assert result.returncode and (w/'projects.generated.bzl').read_bytes()==generated
    restore()
    subprocess.run(cmd+['run','//:sync','--','--check'],cwd=w,check=True,stdout=subprocess.DEVNULL)
finally:
    restore()
    subprocess.run(cmd+['shutdown'],cwd=w,check=True)
