"""Experimental direct-cache publication with action-local bundle validation."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from cache_service import CacheService
from action_publication_control import run as publication_control
from workload import ROOT,SDK,BAZEL,fixture,environment,hashes,shutdown,remove


def run(a):
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);packages=out/'packages';packages.mkdir()
    source=fixture(out/'bootstrap','diamond',packages,restore=False)
    config=source/'NuGet.Config';config.write_text('<configuration><packageSources><clear/><add key="nuget" value="https://api.nuget.org/v3/index.json"/></packageSources></configuration>')
    for project,package,version in [('N0001','Newtonsoft.Json','13.0.1'),('N0002','PolySharp','1.15.0')]:
        p=source/project/(project+'.csproj');p.write_text(p.read_text().replace('</Project>',f'<ItemGroup><PackageReference Include="{package}" Version="{version}" /></ItemGroup></Project>'))
    if a.package_origin_outputs:
        project=source/'N0001/N0001.csproj'
        project.write_text(project.read_text().replace('</Project>','<PropertyGroup><OutputType>Exe</OutputType></PropertyGroup></Project>'))
        (source/'N0001/Program.cs').write_text('public static class NestedProgram { public static void Main() {} }\n')
    value=source/'N0001/Value.cs';value.write_text(value.read_text().replace('2L','Newtonsoft.Json.JsonConvert.DeserializeObject<long>("2")'))
    restored=subprocess.run([str(SDK/'dotnet'),'msbuild','N0003/N0003.csproj','-t:Restore','-p:RestorePackagesWithLockFile=true','-p:RestorePackagesPath='+str(packages),'-p:RestoreConfigFile='+str(config),'-p:Configuration=Release','-p:TargetFramework=net10.0','-p:NuGetAudit=false','-nodeReuse:false','-nologo'],cwd=source,env=environment(source,packages),capture_output=True,text=True,timeout=300)
    (out/'restore.log').write_text(restored.stdout+restored.stderr);assert restored.returncode==0,restored.stderr
    records=[];layout=out/'layout.json'
    with CacheService(a.cache_binary,out/'server') as server:
        def invoke(label,base,checkout,actions,expected,upload=True,direct=True,endpoint=None):
            request=dict(schemaVersion=1,repository=str(ROOT),sdkRoot=str(SDK),bazel=str(BAZEL),workspace=str(checkout),state=str(base/'state'),output=str(out/label),entry='N0003/N0003.csproj',operation='build',**{'nuget-packages':str(packages),'project-actions':True,'direct-checkout':True,'bazel-repository-cache':str(a.repositories.resolve()),'bazel-remote-cache':endpoint or server.url,'bazel-remote-upload':upload})
            if layout.exists():request['project-layout']=str(layout)
            if actions and a.package_origin_outputs:request['package-origin-outputs']=True
            if actions:request.update({'locked-restore':True,'package-actions':True,'experimental-direct-action-cache':direct,'action-local-validation':True})
            path=out/(label+'-request.json');path.write_text(json.dumps(request))
            with (out/(label+'.log')).open('w') as log:
                result=subprocess.run([str(SDK/'dotnet'),str(ROOT/'tools/Preparation/bin/Release/net10.0/Preparation.dll'),'owned-workflow','--request',str(path)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=900)
            report=json.loads((out/label/'report.json').read_text());assert result.returncode==0 and report['accepted'],label
            if actions:assert report['actionLocalValidation'] and report['cachePublication']==('action-experimental' if direct else 'workflow-gated')
            app=base/'state/g/bazel-bin/build.bundle/app';actual=subprocess.check_output([str(SDK/'dotnet'),str(app/'N0003.dll')],text=True).strip();assert actual==expected,(label,actual)
            record={k:report[k] for k in ['seconds','compiles','NugetExtractPackage','MsbuildCompileProject','MsbuildDiscover','MsbuildLockedRestore']};record.update(case=label,applicationOutput=actual,hashes=hashes(app),cachePublication=report['cachePublication'],phases=report['phases']);records.append(record);(out/'report.json').write_text(json.dumps(records,indent=2));print(label,record['seconds'],record['NugetExtractPackage'],record['compiles'],flush=True)
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
            if a.package_origin_outputs:
                seals=list((producer/'state/g/bazel-bin').glob('project_*.api/bundle.json'))
                produced['packageOriginApiBundles']=sum(json.loads(p.read_text())['schemaVersion']==3 for p in seals)
                assert produced['packageOriginApiBundles']>=2
                assert any(json.loads((p.parent/'results.json').read_text())['project']=='N0001/N0001.csproj' and json.loads(p.read_text())['schemaVersion']==3 for p in seals)
                (out/'report.json').write_text(json.dumps(records,indent=2))
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
            materialized={}
            for package in ['newtonsoft.json/13.0.1','polysharp/1.15.0']:
                tree=recovery/'state/g/bazel-bin'/('nuget_'+hashlib.sha256(package.encode()).hexdigest()+'.package')
                materialized[package]=sum(file.is_file() for file in tree.rglob('*'))
            assert materialized['newtonsoft.json/13.0.1']>0,materialized
            if not a.package_origin_outputs:assert materialized['polysharp/1.15.0']==0,materialized
            changed['packageFilesMaterialized']=materialized;(out/'report.json').write_text(json.dumps(records,indent=2))
            if a.package_origin_outputs:
                value=recovery/'source/N0003/Value.cs';value.write_text(value.read_text().replace('4L','14L'))
                changed_entry=invoke('changed-entry',recovery,recovery/'source',True,'31',False)
                assert changed_entry['compiles']==1
            if not a.acceptance_only:
                with CacheService(a.cache_binary,out/'measure-gated-cache') as gated_cache, CacheService(a.cache_binary,out/'measure-direct-cache') as direct_cache:
                    modes={'gated':gated_cache,'direct':direct_cache}
                    for mode,cache in modes.items():
                        invoke(mode+'-cold',out/mode,source,True,'11',direct=mode=='direct',endpoint=cache.url)
                    original=(source/'N0001/Value.cs').read_text()
                    for index in range(1,4):
                        (source/'N0001/Value.cs').write_text(original.replace('("2")',f'("{2+10*index}")'))
                        for mode in (['direct','gated'] if index%2 else ['gated','direct']):
                            record=invoke(mode+'-changed-'+str(index),out/mode,source,True,str(11+10*index),direct=mode=='direct',endpoint=modes[mode].url)
                            assert record['compiles']==1 and record['MsbuildDiscover']['executed']==0
                    (source/'N0001/Value.cs').write_text(original)
            controls=out/'publication-controls';controls.mkdir()
            publication_control(recovery/'state/g',controls,server.url,a.repositories.resolve())
        finally:
            for base in [out/'bootstrap',out/'producer',out/'recovery',out/'gated',out/'direct']:
                if (base/'state/g').exists():shutdown(base)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--repositories',type=Path,required=True);p.add_argument('--cache-binary',type=Path,required=True);p.add_argument('--acceptance-only',action='store_true');p.add_argument('--package-origin-outputs',action='store_true');run(p.parse_args())
