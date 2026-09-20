"""Use locked xUnit v3/MTP archives to build and directly execute a Bazel test."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
SDK=Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
BAZEL=Path(os.environ['RULES_MSBUILD_BAZEL'])


def run(folder, lock):
    workspace=folder/'src'
    assets=json.loads((lock/'obj/project.assets.json').read_text())
    target=assets['targets']['net10.0']
    packages=workspace/'packages'; packages.mkdir(exist_ok=True)
    build=['load("@rules_msbuild//msbuild:defs.bzl", "msbuild_nuget_package")']
    for key, record in target.items():
        name, version=key.split('/')
        archive_name=name.lower()+'.'+version+'.nupkg'
        archive=lock/'packages'/name.lower()/version/archive_name
        shutil.copyfile(archive,packages/archive_name)
        deps=[':'+dep.lower() for dep in record.get('dependencies',{})]
        build.append('msbuild_nuget_package(name='+json.dumps(name.lower())+', package_id='+json.dumps(name)+', version='+json.dumps(version)+', archive='+json.dumps(archive_name)+', content_hash='+json.dumps(assets['libraries'][key]['sha512'])+', archive_sha256='+json.dumps(hashlib.sha256(archive.read_bytes()).hexdigest())+', deps='+json.dumps(deps)+', visibility=["//visibility:public"])')
    (packages/'BUILD.bazel').write_text('\n'.join(build)+'\n')
    test=workspace/'Mtp';test.mkdir(exist_ok=True)
    (test/'Mtp.csproj').write_text((ROOT/'tests/explicit_msbuild/fixtures/Mtp.csproj').read_text())
    test_file=test/'Tests.cs'
    test_file.write_text('public class Tests { [Xunit.Fact] public void Passes() { Xunit.Assert.Equal(7, 7); } }')
    (test/'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl", "msbuild_test")
msbuild_test(name="Mtp", project="Mtp.csproj", target_framework="net10.0", srcs=["Tests.cs"], deps=["//packages:xunit.v3.mtp-v2"], build_deps=["//packages:xunit.v3.mtp-v2"], analyzers=["//packages:xunit.analyzers"], msbuild_properties={"UseMicrosoftTestingPlatformRunner":"true"}, size="small")
''')
    if os.environ.get('RULES_MSBUILD_EXPLICIT_WORKER') == '1':
        build_file=test/'BUILD.bazel'
        build_file.write_text(build_file.read_text().replace('msbuild_test(', 'msbuild_test(linux_worker=True, '))
    def bazel(case, success=True):
        p=subprocess.run([str(BAZEL),'--output_user_root='+str(folder/'user'),'--output_base='+str(folder/'base'),'--ignore_all_rc_files','test','//Mtp','--test_output=all','--strategy=MSBuildAssembly=worker,local','--worker_max_instances=MSBuildAssembly=1','--repository_cache='+os.environ.get('RULES_MSBUILD_REPOSITORY_CACHE', str(folder/'repository-cache'))],cwd=workspace,capture_output=True,text=True,timeout=240)
        output=p.stdout+p.stderr;(folder/(case+'.log')).write_text(output)
        assert (p.returncode==0)==success,(case,output[-8000:])
        print(case,p.returncode,flush=True)
        return output
    passed=bazel('mtp-pass')
    assert 'Microsoft.Testing.Platform v2 Runner' in passed, passed[-4000:]
    project=test/'Mtp.csproj'; original=project.read_text()
    project.write_text(original.replace('Version="4.0.0"','Version="4.0.0" PrivateAssets="all"'))
    assert 'PrivateAssets disagrees' in bazel('mtp-package-metadata',False)
    project.write_text(original.replace('Version="4.0.0"','Version="0.0.1"'))
    assert 'PackageReference version disagrees with lock' in bazel('mtp-package-version',False)
    project.write_text(original)
    test_file.write_text(test_file.read_text().replace('Equal(7, 7)','Equal(7, 8)'))
    failed=bazel('mtp-fail',False)
    assert 'Assert.Equal() Failure' in failed, failed[-4000:]
    test_file.write_text(test_file.read_text().replace('Equal(7, 8)','Equal(7, 7)'))
    bazel('mtp-recovered')
    (folder/'mtp-report.json').write_text(json.dumps(dict(passed=True,failurePropagated=True,recovered=True,packageCount=len(target)),indent=2))


if __name__=='__main__':run(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
