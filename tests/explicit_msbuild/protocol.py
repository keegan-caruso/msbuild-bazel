"""Small, real test-framework projects exercising the Bazel test contract on Linux."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

RULES = Path(__file__).resolve().parents[2]
SDK = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
BAZEL = Path(os.environ['RULES_MSBUILD_BAZEL'])


def command(args, cwd, log):
    p = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, text=True)
    log.write_text(p.stdout + p.stderr)
    return p


def packages(lock, workspace):
    assets = json.loads((lock/'obj/project.assets.json').read_text())
    directory = workspace/'packages'; directory.mkdir(exist_ok=True)
    rows = ['load("@rules_msbuild//msbuild:defs.bzl", "msbuild_nuget_package")']
    for key, record in assets['targets']['net10.0'].items():
        name, version = key.split('/')
        archive = name.lower()+'.'+version+'.nupkg'
        source = lock/'packages'/name.lower()/version/archive
        shutil.copyfile(source, directory/archive)
        attrs = dict(name=name.lower(), package_id=name, version=version, archive=archive, content_hash=assets['libraries'][key]['sha512'], archive_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), deps=[':'+d.lower() for d in record.get('dependencies', {})], visibility=['//visibility:public'])
        rows.append('msbuild_nuget_package('+','.join(k+'='+json.dumps(v) for k,v in attrs.items())+')')
    (directory/'BUILD.bazel').write_text('\n'.join(rows)+'\n')


def setup(folder):
    workspace = folder/'src'; workspace.mkdir(parents=True, exist_ok=True)
    (workspace/'MODULE.bazel').write_text(f'''module(name="test_protocol")
bazel_dep(name="rules_msbuild", version="0.0.0")
local_path_override(module_name="rules_msbuild", path={json.dumps(str(RULES))})
sdk = use_repo_rule("@rules_msbuild//bazel:msbuild.bzl", "local_dotnet_sdk")
sdk(name="dotnet", path={json.dumps(str(SDK))})
register_toolchains("//:registered")
''')
    (workspace/'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:toolchain.bzl", "msbuild_toolchain")
msbuild_toolchain(name="implementation", dotnet="@dotnet//:sdk/dotnet", sdk="@dotnet//:files", runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll", runner_support=["@rules_msbuild//tools/ExplicitBuild:files"], runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered", toolchain=":implementation", toolchain_type="@rules_msbuild//msbuild:toolchain_type")
''')
    test = workspace/'Mtp'; test.mkdir(exist_ok=True)
    project = '''<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType><UseMicrosoftTestingPlatformRunner>true</UseMicrosoftTestingPlatformRunner></PropertyGroup><ItemGroup><PackageReference Include="xunit.v3.mtp-v2" Version="4.0.0"/><PackageReference Include="Microsoft.Testing.Extensions.TrxReport" Version="2.3.3"/></ItemGroup></Project>'''
    (test/'Mtp.csproj').write_text(project)
    lock = folder/'lock'; lock.mkdir(exist_ok=True); (lock/'Lock.csproj').write_text(project)
    p = command([SDK/'dotnet', 'restore', lock/'Lock.csproj', '--packages', lock/'packages', '-p:NuGetAudit=false'], folder, folder/'restore.log')
    assert p.returncode == 0, p.stdout+p.stderr
    packages(lock, workspace)
    (test/'Tests.cs').write_text('''using System; using System.IO; using Xunit;
public class Tests {
 [Fact] public void Passes() {
  Console.WriteLine("live-test-output");
  File.WriteAllText("logs/output.txt", "declared test output");
  var mode=Environment.GetEnvironmentVariable("CASE");
  if(mode=="crash") Environment.Exit(17);
  if(mode=="hang") System.Threading.Thread.Sleep(120000);
  Assert.True(mode!="fail", "intentional assertion failure");
  File.WriteAllText(Path.Combine(Environment.GetEnvironmentVariable("TEST_UNDECLARED_OUTPUTS_DIR")!,"attachment.txt"),"retained attachment");
 }
 [Theory] [InlineData(1)] [InlineData(2)] public void Parameterized(int n) { Assert.True(n>0); }
 [Fact(Skip="intentional skip")] public void Skipped() { }
}
''')
    (test/'BUILD.bazel').write_text('''load("@rules_msbuild//msbuild:defs.bzl", "msbuild_test")
msbuild_test(name="Mtp", project="Mtp.csproj", target_framework="net10.0", srcs=["Tests.cs"], deps=["//packages:xunit.v3.mtp-v2", "//packages:microsoft.testing.extensions.trxreport"], build_deps=["//packages:xunit.v3.mtp-v2", "//packages:microsoft.testing.extensions.trxreport"], analyzers=["//packages:xunit.analyzers"], msbuild_properties={"UseMicrosoftTestingPlatformRunner":"true"}, test_protocol="mtp", test_output_dirs=["logs"], test_filter_argument="--filter-query", linux_worker=True, size="small")
''')
    return workspace


def run(folder):
    workspace = setup(folder)
    startup = [BAZEL, '--host_jvm_args=-Xmx768m', '--output_base='+str(folder/'base'), '--ignore_all_rc_files']
    rows = []
    def test(name, flags=(), success=True):
        p = command(startup+['test', '//Mtp', '--test_output=all', '--strategy=MSBuildAssembly=worker', '--worker_max_instances=MSBuildAssembly=1', '--jobs=4', '--disk_cache=', '--remote_cache=', '--build_event_json_file='+str(folder/(name+'.bep')), *flags], workspace, folder/(name+'.log'))
        assert (p.returncode == 0) == success, (name, (p.stdout+p.stderr)[-6000:])
        xml = workspace/'bazel-testlogs/Mtp/Mtp/test.xml'
        shutil.copyfile(xml, folder/(name+'.xml'))
        root = ET.parse(xml).getroot()
        rows.append(dict(case=name, exit=p.returncode, tests=len(root.findall('.//testcase')), failures=len(root.findall('.//failure')), errors=len(root.findall('.//error')), skipped=len(root.findall('.//skipped'))))
        print(rows[-1], flush=True)
        return root
    try:
        xml = test('pass'); assert (workspace/'bazel-testlogs/Mtp/Mtp/test.outputs/files/logs/output.txt').read_text()=='declared test output'; assert len(xml.findall('.//testcase')) == 4 and len(xml.findall('.//skipped')) == 1
        test('failure', ['--test_env=CASE=fail'], False)
        test('crash', ['--test_env=CASE=crash'], False)
        test('filter', ['--test_filter=/*/*/Tests/Passes'])
        test('empty', ['--test_filter=/*/*/Tests/Absent'], False)
        test('timeout', ['--test_env=CASE=hang', '--test_timeout=3'], False)
        test('recovered')
    finally:
        (folder/'results.json').write_text(json.dumps(rows, indent=2)+'\n')
        subprocess.run(startup+['shutdown'], cwd=workspace, check=True)


if __name__ == '__main__': run(Path(sys.argv[1]).resolve())
