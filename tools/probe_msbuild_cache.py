"""Pinned upstream MSBuildCache compatibility probe, not a cache performance test."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import time
import urllib.request
import zipfile

from prepare_graph import ROOT, DOTNET_ROOT
from probe_graph_cache import cache_environment
from synthetic_graph import generate, name, oracle

VERSION = '0.1.340-preview'
SHA256 = 'f5b19cc753c38cb1dff5644e5da8efdd4b473cc13f943772e8f813a1c5672fac'
REVISION = '54bcfb23a927bead6622eee0cd3f109ae66c9931'
URL = f'https://api.nuget.org/v3-flatcontainer/microsoft.msbuildcache.local/{VERSION}/microsoft.msbuildcache.local.{VERSION}.nupkg'


def probe(output, package=None):
    output=output.resolve();output.mkdir(parents=True,exist_ok=False)
    archive=output/'upstream.nupkg'
    if package: shutil.copyfile(package,archive)
    else:
        with urllib.request.urlopen(URL,timeout=60) as response, archive.open('wb') as stream:shutil.copyfileobj(response,stream)
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==SHA256,'upstream archive hash mismatch'
    extracted=output/'package'
    with zipfile.ZipFile(archive) as z:
        entries=z.namelist()
        assert all(not Path(n).is_absolute() and '..' not in Path(n).parts and '\\' not in n for n in entries)
        z.extractall(extracted)
    assembly=extracted/'build/net9.0/Microsoft.MSBuildCache.Local.dll'
    data=assembly.read_bytes();pe=struct.unpack_from('<I',data,0x3c)[0];machine=hex(struct.unpack_from('<H',data,pe+4)[0])
    report=dict(scope='macOS SDK compatibility; no cache hit or speedup claimed',accepted=False,cacheReuseQualified=False,version=VERSION,packageSha256=SHA256,upstreamRevision=REVISION,peMachine=machine,packageEntries=entries,runs=[])
    dotnet=DOTNET_ROOT/'dotnet'
    def run(label,args,cwd,extra=None):
        t=time.perf_counter();result=subprocess.run(list(map(str,args)),cwd=cwd,env=dict(cache_environment(output,cwd),**(extra or {})),capture_output=True,text=True,timeout=300)
        log=result.stdout+result.stderr;(output/(label+'.log')).write_text(log)
        record=dict(label=label,command=list(map(str,args)),returncode=result.returncode,seconds=time.perf_counter()-t,
            compilerInvocations=sum('/Roslyn/bincore/csc' in line and ' /noconfig ' in line for line in log.splitlines()))
        report['runs'].append(record)
        print(label,result.returncode,flush=True)
        return result,record
    subject=output/'source';spec=generate(subject,10,'fan');entry=spec['entry']
    subprocess.run(['git','init',str(subject)],check=True,capture_output=True)
    (subject/'.gitignore').write_text('**/bin/\n**/obj/\n.nuget/\n')
    p=subject/'Directory.Build.props';p.write_text(p.read_text().replace('</Project>',f'<Import Project="{extracted}/build/Microsoft.MSBuildCache.Local.props" /></Project>'))
    targets=subject/'Directory.Build.targets';targets.write_text(f'<Project><Import Project="{extracted}/build/Microsoft.MSBuildCache.Local.targets" /></Project>')
    subprocess.run(['git','-C',str(subject),'add','.'],check=True,capture_output=True)
    subprocess.run(['git','-C',str(subject),'-c','user.name=Cache probe','-c','user.email=probe@example.invalid','-c','core.hooksPath=/dev/null','commit','-m','Generated compatibility fixture'],check=True,capture_output=True)
    base=[dotnet,'msbuild',entry,'-p:Configuration=Release','-p:TargetFramework=net10.0','-m:2','-nodeReuse:false','-nologo']
    build=[*base,'-t:Build','-graphBuild','-verbosity:normal']
    try:
        result,_=run('restore',[*base,'-t:Restore','-p:MSBuildCacheEnabled=false'],subject);assert result.returncode==0
        result,record=run('baseline',[*build,'-p:MSBuildCacheEnabled=false'],subject);assert result.returncode==0 and record['compilerInvocations']==10
        result,_=run('baseline-app',[dotnet,subject/name(9)/'bin/Release/net10.0/N0009.dll'],subject);assert result.stdout.strip()==oracle(spec['edges'])
        run('file-access-reporting',[*build,'-p:MSBuildCacheEnabled=false','-reportFileAccesses'],subject)
        settings=[f'-p:MSBuildCacheLocalCacheRootPath={output}/cache',f'-p:MSBuildCacheLogDirectory={output}/plugin-logs']
        run('upstream-enabled',[*build,*settings,'-reportFileAccesses'],subject)
        run('upstream-load-only',[*build,*settings],subject)
        result,_=run('capability-bootstrap',[dotnet,'build',ROOT/'tools/CacheCapabilityProbe','-c','Release','--nologo'],ROOT);assert result.returncode==0
        targets.write_text(f'<Project><ItemGroup><ProjectCachePlugin Include="{ROOT}/tools/CacheCapabilityProbe/bin/Release/net10.0/CacheCapabilityProbe.dll" /></ItemGroup></Project>')
        for folder in subject.glob('N*/bin'):shutil.rmtree(folder)
        for folder in subject.glob('N*/obj/Release'):shutil.rmtree(folder)
        for case,expected in [('cold',10),('warm',0)]:
            callback_report=output/(case+'-callbacks.json')
            result,record=run('capability-'+case,[*build,'-p:MSBuildCacheEnabled=false'],subject,dict(MSBUILD_CACHE_PROBE_REPORT=str(callback_report),MSBUILD_CACHE_PROBE_ASSEMBLY=str(assembly)))
            assert result.returncode==0 and record['compilerInvocations']==expected
            callbacks=json.loads(callback_report.read_text());assert callbacks['graphNodes']==10 and callbacks['cacheQueries']==10 and callbacks['projectFinished']==10
            result,_=run('capability-'+case+'-app',[dotnet,subject/name(9)/'bin/Release/net10.0/N0009.dll'],subject);assert result.stdout.strip()==oracle(spec['edges'])
        report['accepted']=True
        report['upstreamInvocationSucceeded']=all(r['returncode']==0 for r in report['runs'] if r['label'] in ('file-access-reporting','upstream-enabled'))
    except BaseException as error:report['failure']=str(error);raise
    finally:(output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--package',type=Path)
    a=p.parse_args();probe(a.output,a.package)
