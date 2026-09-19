"""Owned NuGet directory actions through restore, build and fresh remote recovery."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from cache_service import CacheService
from workload import ROOT,SDK,BAZEL,fixture,environment,hashes,shutdown,remove


def run(a):
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);packages=out/'packages';packages.mkdir()
    source=fixture(out/'bootstrap','diamond',packages,restore=False)
    config=source/'NuGet.Config';config.write_text('<configuration><packageSources><clear/><add key="nuget" value="https://api.nuget.org/v3/index.json"/></packageSources></configuration>')
    for project,package,version in [('N0001','Newtonsoft.Json','13.0.1'),('N0002','PolySharp','1.15.0')]:
        p=source/project/(project+'.csproj');p.write_text(p.read_text().replace('</Project>',f'<ItemGroup><PackageReference Include="{package}" Version="{version}" /></ItemGroup></Project>'))
    value=source/'N0001/Value.cs';value.write_text(value.read_text().replace('2L','Newtonsoft.Json.JsonConvert.DeserializeObject<long>("2")'))
    restored=subprocess.run([str(SDK/'dotnet'),'msbuild','N0003/N0003.csproj','-t:Restore','-p:RestorePackagesWithLockFile=true','-p:RestorePackagesPath='+str(packages),'-p:RestoreConfigFile='+str(config),'-p:Configuration=Release','-p:TargetFramework=net10.0','-p:NuGetAudit=false','-nodeReuse:false','-nologo'],cwd=source,env=environment(source,packages),capture_output=True,text=True,timeout=300)
    (out/'restore.log').write_text(restored.stdout+restored.stderr);assert restored.returncode==0,restored.stderr
    records=[];layout=out/'layout.json'
    with CacheService(a.cache_binary,out/'server') as server:
        def invoke(label,base,checkout,actions,expected,upload=True):
            request=dict(schemaVersion=1,repository=str(ROOT),sdkRoot=str(SDK),bazel=str(BAZEL),workspace=str(checkout),state=str(base/'state'),output=str(out/label),entry='N0003/N0003.csproj',operation='build',**{'nuget-packages':str(packages),'project-actions':True,'direct-checkout':True,'bazel-repository-cache':str(a.repositories.resolve()),'bazel-remote-cache':server.url,'bazel-remote-upload':upload})
            if layout.exists():request['project-layout']=str(layout)
            if actions:request.update({'locked-restore':True,'package-actions':True})
            path=out/(label+'-request.json');path.write_text(json.dumps(request))
            with (out/(label+'.log')).open('w') as log:
                result=subprocess.run([str(SDK/'dotnet'),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),'owned-workflow','--request',str(path)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=900)
            report=json.loads((out/label/'report.json').read_text());assert result.returncode==0 and report['accepted'],label
            app=base/'state/g/bazel-bin/build.bundle/app';actual=subprocess.check_output([str(SDK/'dotnet'),str(app/'N0003.dll')],text=True).strip();assert actual==expected,(label,actual)
            record={k:report[k] for k in ['seconds','compiles','NugetExtractPackage','MsbuildCompileProject','MsbuildDiscover','MsbuildLockedRestore']};record.update(case=label,applicationOutput=actual,hashes=hashes(app));records.append(record);(out/'report.json').write_text(json.dumps(records,indent=2));print(label,record['seconds'],record['NugetExtractPackage'],record['compiles'],flush=True)
            return record
        try:
            legacy=invoke('legacy',out/'bootstrap',source,False,'11')
            layout.write_bytes((out/'legacy/project-layout.json').read_bytes())
            shutdown(out/'bootstrap')
            for p in list(source.rglob('obj')):
                if p.is_dir():remove(p)
            producer=out/'producer';producer.mkdir();shutil.copytree(source,producer/'source')
            produced=invoke('produced',producer,producer/'source',True,'11')
            assert produced['NugetExtractPackage']==dict(executed=2,remoteHits=0)
            assert produced['hashes']==legacy['hashes']
            shutdown(producer);remove(producer)
            recovery=out/'recovery';recovery.mkdir();shutil.copytree(source,recovery/'source')
            recovered=invoke('recovered',recovery,recovery/'source',True,'11',False)
            assert recovered['compiles']==0 and recovered['NugetExtractPackage']==dict(executed=0,remoteHits=2)
            assert recovered['hashes']==produced['hashes']
            trees=list((recovery/'state/g/bazel-bin').glob('nuget_*.package'))
            materialized=[file for tree in trees for file in tree.rglob('*') if file.is_file()]
            assert not materialized,'Fresh cache recovery unexpectedly downloaded package payloads'
            recovered['emptyPackagePlaceholders']=len(trees);recovered['packageFilesMaterialized']=len(materialized);(out/'report.json').write_text(json.dumps(records,indent=2))
            value=recovery/'source/N0001/Value.cs';value.write_text(value.read_text().replace('("2")','("12")'))
            changed=invoke('changed',recovery,recovery/'source',True,'21',False)
            assert changed['compiles']==1 and changed['MsbuildDiscover']['executed']==0 and changed['NugetExtractPackage']['executed']==0
        finally:
            for base in [out/'bootstrap',out/'producer',out/'recovery']:
                if (base/'state/g').exists():shutdown(base)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--repositories',type=Path,required=True);p.add_argument('--cache-binary',type=Path,required=True);run(p.parse_args())
