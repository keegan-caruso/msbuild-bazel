"""Qualify friend assembly access, reference invalidation and relocated cache recovery.

Run with RULES_MSBUILD_DOTNET_ROOT and RULES_MSBUILD_BAZEL in the Linux worker
container. No external packages or test framework are required: executable Bazel
tests assert behavior and retain the actual loaded implementation hash.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
BAZEL = Path(os.environ['RULES_MSBUILD_BAZEL'])
LIBRARY = '''using System.Runtime.CompilerServices;
[assembly: InternalsVisibleTo("Fixture.Tests")]
public static class PublicApi { public static int Read() => Secrets.Get(); }
internal static class Secrets {
 internal static int Get() => 7;
 internal const int Number = 3;
 internal static int Generic<T>() where T : class => 1;
}
'''
TEST = '''using System;
using System.IO;
using System.Security.Cryptography;
var value = Secrets.Get();
var digest = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(PublicApi).Assembly.Location)));
var witness = $"value={value};constant={Secrets.Number};implementation={digest}";
Console.WriteLine(witness);
if (Environment.GetEnvironmentVariable("TEST_UNDECLARED_OUTPUTS_DIR") is { } output)
 File.WriteAllText(Path.Combine(output, "implementation.txt"), witness);
return value == 7 && Secrets.Number == 3 && Secrets.Generic<string>() == 1 ? 0 : 1;
'''


def invoke(args, cwd, log):
    p = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True, text=True, timeout=240)
    log.write_text(p.stdout + p.stderr)
    return p


def setup(folder):
    workspace = folder/'producer'; workspace.mkdir(parents=True)
    def put(name, text):
        path = workspace/name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
    put('MODULE.bazel', f'''module(name="ivt_qualification")
bazel_dep(name="rules_msbuild",version="0.0.0")
local_path_override(module_name="rules_msbuild",path={json.dumps(str(ROOT))})
sdk=use_repo_rule("@rules_msbuild//bazel:msbuild.bzl","local_dotnet_sdk")
sdk(name="dotnet",path={json.dumps(str(SDK))})
register_toolchains("//:registered")
''')
    put('BUILD.bazel', '''load("@rules_msbuild//msbuild:toolchain.bzl","msbuild_toolchain")
msbuild_toolchain(name="implementation",dotnet="@dotnet//:sdk/dotnet",sdk="@dotnet//:files",runner="@rules_msbuild//tools/ExplicitBuild:bin/Release/net10.0/ExplicitBuild.dll",runner_support=["@rules_msbuild//tools/ExplicitBuild:files"],runtime_manifest="@dotnet//:runtime-roots.json")
toolchain(name="registered",toolchain=":implementation",toolchain_type="@rules_msbuild//msbuild:toolchain_type")
''')
    for name, assembly, code in [('Library','Fixture.Library',LIBRARY),('Friend','Fixture.Tests',TEST),('Stranger','Fixture.Stranger','return Secrets.Get();')]:
        properties='<TargetFramework>net10.0</TargetFramework><AssemblyName>'+assembly+'</AssemblyName>'
        if name != 'Library': properties += '<OutputType>Exe</OutputType>'
        refs='' if name=='Library' else '<ItemGroup><ProjectReference Include="../Library/Library.csproj"/></ItemGroup>'
        put(name+'/'+name+'.csproj','<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup>'+properties+'</PropertyGroup>'+refs+'</Project>')
        put(name+'/Code.cs',code)
        rule='msbuild_library' if name=='Library' else 'msbuild_test'
        deps='' if name=='Library' else ',deps=["//Library:target"]'
        put(name+'/BUILD.bazel',f'load("@rules_msbuild//msbuild:defs.bzl","{rule}")\n{rule}(name="target",project="{name}.csproj",assembly_name="{assembly}",target_framework="net10.0",srcs=["Code.cs"],linux_worker=True,visibility=["//visibility:public"]{deps})\n')
    return workspace


def main(folder):
    workspace=setup(folder); base=folder/'producer-base'; records=[]
    def start(): return [BAZEL,'--host_jvm_args=-Xmx768m','--output_base='+str(base),'--ignore_all_rc_files']
    def run(case, success=True, target='//Friend:target', diagnostic=None, force=False):
        execution=folder/(case+'.execution.json'); bep=folder/(case+'.bep')
        args=start()+['test',target,'//Library:target','--output_groups=+reference','--test_output=all','--jobs=2','--strategy=MSBuildAssembly=worker','--worker_max_instances=MSBuildAssembly=1','--disk_cache='+str(folder/'cache'),'--remote_cache=','--execution_log_json_file='+str(execution),'--build_event_json_file='+str(bep)]
        if force: args.append('--nocache_test_results')
        p=invoke(args,workspace,folder/(case+'.log'))
        assert (p.returncode==0)==success,(case,(p.stdout+p.stderr)[-5000:])
        if diagnostic: assert diagnostic in p.stdout+p.stderr,(case,diagnostic)
        text=execution.read_text(); actions=[]; decoder=json.JSONDecoder()
        while text.strip():
            row,end=decoder.raw_decode(text.lstrip()); text=text.lstrip()[end:]; actions.append(row)
        builds=[a for a in actions if a.get('mnemonic')=='MSBuildAssembly']
        compiled=sorted(a['targetLabel'] for a in builds if not a.get('cacheHit'))
        events=[json.loads(l) for l in bep.read_text().splitlines()]
        tests=[e['testResult'] for e in events if 'testResult' in e]
        row=dict(case=case,exitCode=p.returncode,compiled=compiled,cacheHits=sorted(a['targetLabel'] for a in builds if a.get('cacheHit')),testExecuted=any(not t.get('cachedLocally') and not t.get('executionInfo',{}).get('cachedRemotely') and t.get('executionInfo',{}).get('strategy')!='disk cache hit' for t in tests),testStatuses=[t['status'] for t in tests])
        witness=workspace/'bazel-testlogs/Friend/target/test.outputs/implementation.txt'
        if tests and target=='//Friend:target' and witness.exists(): row['witness']=witness.read_text()
        records.append(row);print(json.dumps(row),flush=True)
        (folder/'results.json').write_text(json.dumps(records,indent=2)+'\n')
        return row
    def digest():return hashlib.sha256((workspace/'bazel-bin/Library/target.reference/Fixture.Library.dll').read_bytes()).hexdigest()
    def raw(case, success=True, diagnostic=None, project='Friend'):
        dest=folder/('raw-'+case)
        shutil.copytree(workspace,dest,ignore=shutil.ignore_patterns('bazel-*','bin','obj'))
        p=invoke([SDK/'dotnet','build',dest/project/(project+'.csproj'),'-c','Release','-p:NuGetAudit=false','-p:UseSharedCompilation=false','-nodeReuse:false'],dest,folder/(case+'.raw.log'))
        assert (p.returncode==0)==success,(case,p.stdout+p.stderr)
        if diagnostic: assert diagnostic in p.stdout+p.stderr,(case,diagnostic)
        shutil.rmtree(dest)
    def baseline(case):
        (workspace/'Library/Code.cs').write_text(LIBRARY)
        (workspace/'Friend/Code.cs').write_text(TEST)
        return run(case)
    try:
        raw('baseline'); first=run('baseline'); ref=digest()
        assert first['compiled']==['//Friend:target','//Library:target'] and first['testExecuted']
        unchanged=run('unchanged');assert unchanged['compiled']==[] and not unchanged['testExecuted']
        raw('nonfriend',False,'CS0122','Stranger');run('nonfriend',False,'//Stranger:target','CS0122')
        (workspace/'Library/Code.cs').write_text(LIBRARY.replace('=> 7','=> 8'))
        body=run('body-edit',False);assert body['compiled']==['//Library:target'] and body['testExecuted'] and digest()==ref
        assert 'value=8;' in body['witness'] and body['witness']!=first['witness']
        baseline('body-recovered')
        (workspace/'Library/Code.cs').write_text(LIBRARY.replace('int Get() => 7','int Get(int value) => value').replace('Secrets.Get();','Secrets.Get(7);'))
        raw('signature',False,'CS7036');signature=run('signature',False,diagnostic='CS7036');assert '//Friend:target' in signature['compiled'] and digest()!=ref
        baseline('signature-recovered')
        (workspace/'Library/Code.cs').write_text(LIBRARY.replace('Number = 3','Number = 4'))
        constant=run('constant',False);assert constant['compiled']==['//Friend:target','//Library:target'] and constant['testExecuted'] and digest()!=ref
        assert 'constant=4;' in constant['witness']
        baseline('constant-recovered')
        (workspace/'Library/Code.cs').write_text(LIBRARY.replace('where T : class','where T : struct'))
        raw('constraint',False,'CS0453');constraint=run('constraint',False,diagnostic='CS0453');assert '//Friend:target' in constraint['compiled'] and digest()!=ref
        baseline('constraint-recovered')
        for name,grant in [('grant-removed',''),('grant-renamed','[assembly: InternalsVisibleTo("Wrong.Name")]')]:
            (workspace/'Library/Code.cs').write_text(LIBRARY.replace('[assembly: InternalsVisibleTo("Fixture.Tests")]',grant))
            raw(name,False,'CS0122');row=run(name,False,diagnostic='CS0122');assert '//Friend:target' in row['compiled'] and digest()!=ref
            baseline(name+'-recovered')
        # SDK item declaration must work as well as a source attribute.
        project=workspace/'Library/Library.csproj'; original=project.read_text()
        (workspace/'Library/Code.cs').write_text(LIBRARY.replace('[assembly: InternalsVisibleTo("Fixture.Tests")]',''))
        project.write_text(original.replace('</Project>','<ItemGroup><InternalsVisibleTo Include="Fixture.Tests"/></ItemGroup></Project>'))
        raw('sdk-item');run('sdk-item');project.write_text(original);baseline('sdk-item-recovered')
        # Generate disposable fixture keys with the platform crypto library, not checked-in secrets.
        keytool=folder/'keytool';keytool.mkdir()
        (keytool/'Key.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup></Project>')
        (keytool/'Program.cs').write_text('''using System; using System.IO; using System.Security.Cryptography;
using var rsa=new RSACryptoServiceProvider(2048);
var key=rsa.ExportCspBlob(true); BitConverter.GetBytes(0x2400).CopyTo(key,4); File.WriteAllBytes(args[0],key);
var blob=rsa.ExportCspBlob(false); BitConverter.GetBytes(0x2400).CopyTo(blob,4);
using var stream=new MemoryStream(); using var writer=new BinaryWriter(stream);
writer.Write(0x2400);writer.Write(0x8004);writer.Write(blob.Length);writer.Write(blob);
File.WriteAllText(args[1],Convert.ToHexString(stream.ToArray()));
''')
        p=invoke([SDK/'dotnet','build',keytool/'Key.csproj','-c','Release'],folder,folder/'keytool.log');assert p.returncode==0,p.stdout+p.stderr
        for name in ('key','wrong'):
            p=invoke([SDK/'dotnet',keytool/'bin/Release/net10.0/Key.dll',folder/(name+'.snk'),folder/(name+'.pub')],folder,folder/(name+'.log'));assert p.returncode==0,p.stdout+p.stderr
        public=(folder/'key.pub').read_text()
        originals={}
        for name in ('Library','Friend'):
            proj=workspace/name/(name+'.csproj'); build=workspace/name/'BUILD.bazel'
            originals[proj]=proj.read_text();originals[build]=build.read_text()
            proj.write_text(proj.read_text().replace('</PropertyGroup>','<SignAssembly>true</SignAssembly><AssemblyOriginatorKeyFile>key.snk</AssemblyOriginatorKeyFile></PropertyGroup>'))
            shutil.copyfile(folder/'key.snk',workspace/name/'key.snk')
            build.write_text('load("@rules_msbuild//msbuild:defs.bzl","msbuild_items")\nmsbuild_items(name="key",item_type="None",srcs=["key.snk"])\n'+build.read_text().replace('srcs=["Code.cs"]','srcs=["Code.cs"],items=[":key"]'))
        (workspace/'Library/Code.cs').write_text(LIBRARY.replace('Fixture.Tests','Fixture.Tests, PublicKey='+public))
        raw('signed');run('signed')
        shutil.copyfile(folder/'wrong.snk',workspace/'Friend/key.snk')
        raw('wrong-key',False,'CS0281');wrong=run('wrong-key',False,diagnostic='CS0281');assert wrong['compiled']==['//Friend:target']
        shutil.copyfile(folder/'key.snk',workspace/'Friend/key.snk');run('signed-recovered')
        for path,text in originals.items():path.write_text(text)
        baseline('unsigned-recovered')
        # Relocate authored inputs only. Delete all producer outputs before recovery.
        invoke(start()+['shutdown'],workspace,folder/'shutdown-producer.log')
        relocated=folder/'relocated';shutil.copytree(workspace,relocated,ignore=shutil.ignore_patterns('bazel-*','bin','obj'))
        shutil.rmtree(workspace);shutil.rmtree(base)
        workspace=relocated;base=folder/'consumer-base'
        recovered=run('relocated-recovery',force=True)
        assert recovered['compiled']==[] and set(recovered['cacheHits'])=={'//Library:target','//Friend:target'} and recovered['testExecuted']
        assert recovered['witness']==first['witness'] and digest()==ref
        (workspace/'Library/Code.cs').write_text(LIBRARY.replace('=> 7','=> 9'))
        changed=run('relocated-body-edit',False)
        assert changed['compiled']==['//Library:target'] and changed['testExecuted'] and digest()==ref and 'value=9;' in changed['witness']
        (workspace/'Library/Code.cs').write_text(LIBRARY.replace('"Fixture.Tests"','"No.Friend"'))
        run('relocated-grant-rejection',False,diagnostic='CS0122')
    finally:
        invoke(start()+['shutdown'],workspace,folder/'shutdown.log')
        subprocess.run([str(SDK/'dotnet'),'build-server','shutdown'],cwd=folder,check=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('folder',type=Path);args=parser.parse_args();main(args.folder.resolve())
