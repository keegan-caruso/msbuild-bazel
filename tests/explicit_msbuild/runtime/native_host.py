"""Bind source-built native outputs and managed CoreLib into the declared host."""
import ast
import json
from pathlib import Path
import shutil
import sys
workspace=Path(sys.argv[1]).resolve()
here=Path(__file__).resolve().parent
shutil.copyfile(here/'NativeProbe.cs.txt',workspace/'load_probe/StartupHook.cs')
host=workspace/'runtime'
build=host/'BUILD.bazel'
text=build.read_text()
start=text.index('paths=')+len('paths=');end=text.index(')\nmsbuild_runtime',start)
paths=ast.literal_eval(text[start:end])
framework='shared/Microsoft.NETCore.App/10.0.11'
for name in ['libcoreclr.so','libclrjit.so','System.Private.CoreLib.dll']:
    del paths[framework+'/'+name]
for name in ['libcoreclr.so','libclrjit.so']:
    paths['//native:'+{'libcoreclr.so':'coreclr','libclrjit.so':'jit'}[name]]=framework+'/'+name
corelib='src_coreclr_System.Private.CoreLib_System.Private.CoreLib_net10.0'
paths['//upstream:'+corelib]=framework
build.write_text(text[:start]+json.dumps(paths)+text[end:])
upstream=workspace/'upstream/BUILD.bazel'
lines=upstream.read_text().splitlines()
for i,line in enumerate(lines):
    if line.startswith('msbuild_library(') and ('name="'+corelib+'"' in line or "name='"+corelib+"'" in line):
        assert 'visibility=' not in line
        lines[i]=line[:-1]+',visibility=["//runtime:__pkg__"])'
upstream.write_text('\n'.join(lines)+'\n')
wrapper=host/'host.sh'
s=wrapper.read_text().replace('export DOTNET_ROOT=', 'export DOTNET_ReadyToRun=0\nexport QUALIFICATION_NATIVE="$root/'+framework+'"\nexport DOTNET_ROOT=')
wrapper.write_text(s)
