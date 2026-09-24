"""Exercise XML reuse across changed imports and configuration in one worker."""
import json
import os
from pathlib import Path
import subprocess
import sys

folder=Path(sys.argv[1]).resolve(); workspace=folder/'src'
project=workspace/'State';project.mkdir(exist_ok=True)
(project/'State.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup><Import Project="State.props" /></Project>')
props=project/'State.props'
def content(symbol):
    return '<Project><PropertyGroup><DefineConstants>$(DefineConstants);'+symbol+'</DefineConstants></PropertyGroup></Project>'
props.write_text(content('FIRST'))
(project/'Program.cs').write_text('''using System;
#if FIRST
const string value="first";
#elif OTHER
const string value="other";
#else
#error Import not applied
#endif
#if DEBUG
Console.WriteLine(value+":Debug");
#else
Console.WriteLine(value+":Release");
#endif
''')
(project/'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl", "msbuild_binary")
msbuild_binary(name="State",project="State.csproj",target_framework="net10.0",srcs=["Program.cs"],msbuild_imports=["State.props"],linux_worker=True)
''')
cmd=[os.environ['RULES_MSBUILD_BAZEL'],'--output_base='+str(folder/'xml-base'),'--ignore_all_rc_files']
rows=[]
def run(case,expected,mode='fastbuild',success=True):
    p=subprocess.run(cmd+['run','//State','-c',mode,'--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--disk_cache=','--repository_cache='+os.environ['RULES_MSBUILD_REPOSITORY_CACHE']],cwd=workspace,capture_output=True,text=True,timeout=240)
    (folder/(case+'.log')).write_text(p.stdout+p.stderr)
    assert (p.returncode==0)==success,(case,p.stdout,p.stderr[-4000:])
    if success:
        assert p.stdout.strip()==expected,(case,p.stdout)
        worker=json.loads((workspace/'bazel-bin/State/State.diagnostics/worker.json').read_text())
        rows.append(dict(case=case,output=p.stdout.strip(),processId=worker['processId']))
    else: rows.append(dict(case=case,rejected=True))
    print(case,p.returncode,flush=True)
run('xml-first','first:Release')
timestamp=props.stat().st_mtime_ns
props.write_text(content('OTHER'));os.utime(props,ns=(timestamp,timestamp))
run('xml-same-size-time-import','other:Release')
# A new Bazel configuration may choose a distinct tool output path/worker key.
# Assert reuse separately within each configuration, not across different keys.
run('xml-debug','other:Debug','dbg')
props.write_text(content('FIRST'))
run('xml-debug-import','first:Debug','dbg')
props.write_text('<Project><invalid></Project>')
run('xml-bad-import',None,'dbg',False)
props.write_text(content('OTHER'))
run('xml-recovered','other:Debug','dbg')
assert rows[0]['processId']==rows[1]['processId'],rows
assert rows[2]['processId']==rows[3]['processId']==rows[5]['processId'],rows
(folder/'xml-report.json').write_text(json.dumps(rows,indent=2))
subprocess.run(cmd+['shutdown'],cwd=workspace,check=True)
