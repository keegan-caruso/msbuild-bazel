"""Qualify pinned Bazel dependency reuse with external networking denied."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
from cache_service import CacheService
from workload import BAZEL,ROOT,OFFLINE_PROFILE,fixture,native,shutdown,remove


def run(args):
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    cache=output/'repositories';report=dict(accepted=False,cases=[],scope='same-host dependency-cache controls')
    def save():(output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    # Prove the process policy prevents a real public fetch, rather than merely
    # labeling a warm run offline. Loopback remains available for the native CAS.
    blocked=subprocess.run(['/usr/bin/sandbox-exec','-p',OFFLINE_PROFILE,'/usr/bin/curl','--max-time','5','--fail','https://bcr.bazel.build/bazel_registry.json'],capture_output=True,text=True)
    assert blocked.returncode!=0,blocked.stdout
    report['networkProbe']=dict(exitCode=blocked.returncode,stderr=blocked.stderr)
    try:
        with CacheService(args.cache_binary,output/'server') as service:
            base=output/'producer'/'n';source=fixture(base,'diamond',args.packages,args.checkout)
            try:producer=native(base,source,'diamond',args.packages,service.url+'/native',install_cache=args.install_cache,repository_cache=cache)
            finally:shutdown(base)
            key=producer['remote']['publishedSnapshot'];remove(base)
            base=output/'consumer'/'n';source=fixture(base,'diamond',args.packages,args.checkout)
            try:
                consumer=native(base,source,'diamond',args.packages,service.url+'/native',key,install_cache=args.install_cache,repository_cache=cache,disable_repository_downloads=True)
                assert consumer['compiles']==0 and consumer['managedHashes']==producer['managedHashes']
                assert consumer['applicationOutput']==producer['applicationOutput']
                report['cases'].append(dict(case='repository-downloads-disabled-recovery',passed=True,compiles=0,phases=consumer['phases']))
            finally:shutdown(base)
            install=consumer['bazelInstallBase']
        pin=json.loads((ROOT/'bazel/native.MODULE.bazel.lock').read_text())
        digest=pin['registryFileHashes']['https://bcr.bazel.build/modules/platforms/0.0.11/MODULE.bazel']
        for case in ('warm-offline','missing-object','corrupt-object','outdated-lock'):
            base=output/case;base.mkdir();work=base/'workspace';work.mkdir()
            selected=cache
            if case in ('missing-object','corrupt-object'):
                selected=base/'cache';shutil.copytree(cache,selected)
                target=selected/'content_addressable/sha256'/digest/'file'
                if case=='missing-object':target.unlink()
                else:target.write_bytes(b'poisoned cache object')
            version='0.0.11'
            (work/'MODULE.bazel').write_text('module(name="native_msbuild_workflow")\nbazel_dep(name="platforms", version="'+version+'")\n')
            lock=work/'MODULE.bazel.lock';shutil.copyfile(ROOT/'bazel/native.MODULE.bazel.lock',lock)
            if case=='outdated-lock':
                incomplete=json.loads(lock.read_text());del incomplete['registryFileHashes']['https://bcr.bazel.build/modules/platforms/0.0.11/MODULE.bazel'];lock.write_text(json.dumps(incomplete))
            before=lock.read_bytes()
            hosts=base/'hosts';hosts.write_text('127.0.0.1 localhost\n203.0.113.1 bcr.bazel.build\n')
            startup=[str(BAZEL),'--nosystem_rc','--nohome_rc','--noworkspace_rc','--output_base='+str(base/'b'),'--output_user_root='+str(base/'u'),'--install_base='+install,'--host_jvm_args=-Djdk.net.hosts.file='+str(hosts)]
            try:
                result=subprocess.run(['/usr/bin/sandbox-exec','-p',OFFLINE_PROFILE]+startup+['query','@platforms//cpu:arm64','--incompatible_autoload_externally=','--lockfile_mode=error','--repository_disable_download','--http_timeout_scaling=0.1','--repository_cache='+str(selected)],cwd=work,capture_output=True,text=True,timeout=90)
                (base/'command.log').write_text(result.stdout+result.stderr)
                assert (result.returncode==0)==(case=='warm-offline'),(case,result.stdout,result.stderr)
                assert lock.read_bytes()==before
                report['cases'].append(dict(case=case,passed=True,exitCode=result.returncode,lockUnchanged=True,stderr=result.stderr))
                save()
            finally:subprocess.run(startup+['shutdown'],cwd=work,capture_output=True,check=True)
        report['accepted']=True
    finally:save()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('output','cache-binary','packages','checkout','install-cache'):parser.add_argument('--'+key,type=Path,required=True)
    run(parser.parse_args())
