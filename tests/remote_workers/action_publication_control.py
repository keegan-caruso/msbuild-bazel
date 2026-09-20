"""Real direct-cache control: invalid composed outputs must never be cache hits."""
import hashlib
import json
from pathlib import Path
import subprocess
from workload import BAZEL

RULE = '''def _probe(ctx):
    output = ctx.actions.declare_directory(ctx.label.name + ".app")
    metadata = ctx.actions.declare_directory(ctx.label.name + ".metadata")
    request = ctx.actions.declare_file(ctx.label.name + ".json")
    ctx.actions.write(request, json.encode({"entry":"App/App.csproj", "output":output.path, "bundles":[], "entryBundle":"probe-fixture", "runtimeBundles":[], "metadataOutput":metadata.path,"validatePublication":True}))
    ctx.actions.run(executable=ctx.executable.dotnet, arguments=[ctx.file.runner.path,"--compose-projects",request.path], inputs=depset(ctx.files.inputs+[request,ctx.file.runner],transitive=[ctx.attr.sdk[DefaultInfo].files,ctx.attr.tools[DefaultInfo].files]), outputs=[output,metadata], env={"PATH":"/usr/bin:/bin"}, mnemonic="ValidatePublication", execution_requirements={"block-network":"1"})
    return [DefaultInfo(files=depset([output,metadata]))]
publication_probe = rule(implementation=_probe, attrs={"inputs":attr.label_list(allow_files=True),"sdk":attr.label(),"tools":attr.label(),"runner":attr.label(allow_single_file=True),"dotnet":attr.label(executable=True,cfg="exec",allow_single_file=True)})
'''
TARGET = '''
publication_probe(name="publication_probe", inputs=glob(["probe-fixture/**"]), sdk="@dotnet//:files", tools="@owned_tools//:files", runner="@owned_tools//:tools/NativeProjectCache/bin/Release/net10.0/NativeProjectCache.dll", dotnet="@dotnet//:sdk/dotnet")
'''

def run(generated, out, endpoint, repositories):
    (generated/'publication_probe.bzl').write_text(RULE)
    build=generated/'BUILD.bazel';build.write_text('load(":publication_probe.bzl", "publication_probe")\n'+build.read_text()+TARGET)
    key='1'*64
    bundle=generated/'probe-fixture/cache'/key
    artifact=bundle/'artifacts/App/bin/Release/net10.0/App.dll';artifact.parent.mkdir(parents=True);artifact.write_bytes(b'controlled bundle payload')
    sha=lambda value:hashlib.sha256(value).hexdigest()
    rows=[]
    for label,invalid in [('valid',False),('valid-recovery',False),('invalid',True),('invalid-retry',True)]:
        result=dict(project='App/App.csproj',key=key,inputs='2'*64,toolchain='invalid' if invalid else '3'*64,targetFramework='net10.0',targets={})
        (bundle/'results.json').write_text(json.dumps(result))
        (bundle/'artifacts.json').write_text(json.dumps([dict(path='App/bin/Release/net10.0/App.dll',size=artifact.stat().st_size,sha256=sha(artifact.read_bytes()))]))
        (bundle/'bundle.json').write_text(json.dumps(dict(schemaVersion=1,resultsSha256=sha((bundle/'results.json').read_bytes()),artifactsSha256=sha((bundle/'artifacts.json').read_bytes()))))
        base=out/label;trace=out/(label+'-execution.json')
        startup=[str(BAZEL),'--nosystem_rc','--nohome_rc','--noworkspace_rc','--output_base='+str(base)]
        command=startup+['build','//:publication_probe','--incompatible_autoload_externally=','--lockfile_mode=error','--spawn_strategy=darwin-sandbox','--remote_cache='+endpoint,'--remote_cache_async=true','--remote_upload_local_results=true','--remote_verify_downloads=true','--repository_cache='+str(repositories),'--execution_log_json_file='+str(trace),'--noshow_progress']
        try:
            process=subprocess.run(command,cwd=generated,capture_output=True,text=True,timeout=180)
            (out/(label+'.log')).write_text(process.stdout+process.stderr)
            if invalid:
                assert process.returncode!=0 and 'Invalid CAS digest' in process.stderr,(label,process.stderr)
            else:assert process.returncode==0,(label,process.stderr)
            decoder=json.JSONDecoder();text=trace.read_text();events=[]
            while text.strip():
                event,n=decoder.raw_decode(text.lstrip());events.append(event);text=text.lstrip()[n:]
            action=next(e for e in events if e.get('mnemonic')=='ValidatePublication')
            hit=action.get('cacheHit',False)
            assert hit==(label=='valid-recovery'),(label,action)
            rows.append(dict(case=label,exitCode=process.returncode,cacheHit=hit))
        finally:subprocess.run(startup+['shutdown'],cwd=generated,capture_output=True,timeout=60)
    (out/'report.json').write_text(json.dumps(rows,indent=2)+'\n')
    return rows
