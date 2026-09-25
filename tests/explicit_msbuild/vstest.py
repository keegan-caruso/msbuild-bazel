"""VSTest contract qualification with small xUnit, NUnit, and MSTest projects."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from protocol import RULES, SDK, BAZEL, command, packages


def setup(folder, synchronized=False):
    workspace=folder/'src'
    workspace.mkdir(parents=True, exist_ok=True)
    mappings=dict(packages={}, tests={})
    if synchronized:
        (workspace/'MODULE.bazel').write_text('module(name="synced_vstest")\nbazel_dep(name="rules_msbuild",version="0.0.0")\nlocal_path_override(module_name="rules_msbuild",path='+json.dumps(str(RULES))+')\ndotnet=use_extension("@rules_msbuild//msbuild:extensions.bzl","dotnet")\ndotnet.sdk(name="dotnet",version="10.0.400")\nuse_repo(dotnet,"dotnet")\nregister_toolchains("@dotnet//:all")\n')
    # Reuse the MTP workspace/toolchain; keep framework package graphs independent.
    lock=folder/'vstest-lock';lock.mkdir(exist_ok=True)
    versions={'Microsoft.NET.Test.Sdk':'17.14.1','Microsoft.TestPlatform.CLI':'17.14.1','xunit':'2.9.3','xunit.runner.visualstudio':'3.1.1','NUnit':'4.3.2','NUnit3TestAdapter':'5.0.0','MSTest.TestFramework':'3.8.3','MSTest.TestAdapter':'3.8.3'}
    def project(names):
        return '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><IsTestProject>true</IsTestProject><GenerateProgramFile>false</GenerateProgramFile></PropertyGroup><ItemGroup>'+''.join('<PackageReference Include="'+n+'" Version="'+versions[n]+'"/>' for n in names)+'</ItemGroup></Project>'
    (lock/'Lock.csproj').write_text(project(versions))
    p=command([SDK/'dotnet','restore',lock/'Lock.csproj','--packages',lock/'packages','-p:NuGetAudit=false'],folder,folder/'vstest-restore.log');assert p.returncode==0,p.stdout+p.stderr
    # packages() writes a self-contained package BUILD; place it in a separate subtree.
    tree=workspace/'Vstest';tree.mkdir(exist_ok=True);packages(lock,tree)
    common=['Microsoft.NET.Test.Sdk']
    fixtures={
      'Xunit':(['xunit','xunit.runner.visualstudio'],'using Xunit; public class Tests { [Fact] public void Passes() { Assert.True(System.Environment.GetEnvironmentVariable("CASE")!="fail"); Assert.Equal("tests",System.IO.Path.GetFileName(System.IO.Directory.GetCurrentDirectory())); Assert.Equal("declared",System.IO.File.ReadAllText("input.txt")); System.IO.File.WriteAllText("logs/result.txt","retained"); } [Theory] [InlineData(1)] [InlineData(2)] public void Parameterized(int n) { Assert.True(n>0); } [Fact(Skip="intentional skip")] public void Skipped() { } }','xunit.runner.visualstudio','build/net8.0'),
      'Nunit':(['NUnit','NUnit3TestAdapter'],'using NUnit.Framework; public class Tests { [Test] public void Passes() { Assert.That(System.Environment.GetEnvironmentVariable("CASE"), Is.Not.EqualTo("fail")); } [TestCase(1)] [TestCase(2)] public void Parameterized(int n) { Assert.That(n,Is.GreaterThan(0)); } [Test,Ignore("intentional skip")] public void Skipped() { } }','nunit3testadapter','build/netcoreapp3.1'),
      'Mstest':(['MSTest.TestFramework','MSTest.TestAdapter'],'using Microsoft.VisualStudio.TestTools.UnitTesting; [TestClass] public class Tests { [TestMethod] public void Passes() { Assert.AreNotEqual("fail",System.Environment.GetEnvironmentVariable("CASE")); } [TestMethod] [DataRow(1)] [DataRow(2)] public void Parameterized(int n) { Assert.IsTrue(n>0); } [TestMethod,Ignore("intentional skip")] public void Skipped() { } }','mstest.testadapter','build/net8.0'),
    }
    for name,(deps,code,adapter,path) in fixtures.items():
        dest=tree/name;dest.mkdir(exist_ok=True)
        project_deps=[d for d in deps if name!='Xunit' or d!='xunit.runner.visualstudio']
        (dest/(name+'.csproj')).write_text(project(common+project_deps).replace('<GenerateProgramFile>false</GenerateProgramFile>','<GenerateProgramFile>true</GenerateProgramFile>') if name=='Mstest' else project(common+project_deps));(dest/'Tests.cs').write_text(code)
        project_file=dest/(name+'.csproj')
        project_file.write_text(project_file.read_text().replace('<TargetFramework>', '<AssemblyName>'+name+'.Tests</AssemblyName><TargetFramework>'))
        (dest/'settings.runsettings').write_text('<RunSettings><RunConfiguration><DotNetHostPath>/must-not-use-this-host/dotnet</DotNetHostPath><EnvironmentVariables><FROM_SETTINGS>declared</FROM_SETTINGS></EnvironmentVariables></RunConfiguration></RunSettings>')
        attrs=dict(name=name,assembly_name=name+'.Tests',project=name+'.csproj',target_framework='net10.0',srcs=['Tests.cs'],deps=['//Vstest/packages:'+n.lower() for n in common+project_deps],build_deps=['//Vstest/packages:'+n.lower() for n in common+project_deps],test_protocol='vstest',test_output_type='exe' if name=='Mstest' else 'library',test_runner='//Vstest:tools_runner',test_adapters=['//Vstest:tools_'+name.lower()],test_settings='settings.runsettings',size='small')
        if name=='Xunit':
            (dest/'input.txt').write_text('declared')
            attrs.update(test_working_directory='tests',data_paths={'input.txt':'tests/input.txt'},test_output_dirs=['tests/logs'])
        build='load("@rules_msbuild//msbuild:defs.bzl", "msbuild_test")\n'
        build+='msbuild_test('+','.join(k+'='+json.dumps(v) for k,v in attrs.items())+',linux_worker=True)\n'
        if synchronized:
            for package in common+project_deps:
                mappings['packages'][package+'/'+versions[package]]=dict(label='//Vstest/packages:'+package.lower(),roles=['deps','build_deps'])
            test=dict(protocol='vstest',runner='//test_tools:tools_runner',adapters=['//test_tools:tools_'+name.lower()],settings='Vstest/'+name+'/settings.runsettings',outputType='exe' if name=='Mstest' else 'library')
            if name=='Xunit':
                test.update(workingDirectory='tests',dataPaths={'Vstest/Xunit/input.txt':'tests/input.txt'},outputDirectories=['tests/logs'])
            mappings['tests']['Vstest/'+name+'/'+name+'.csproj']=test
        else:
            (dest/'BUILD.bazel').write_text(build)
    adapters={name.lower():dict(package='//Vstest/packages:'+adapter,path=path) for name,(_,_,adapter,path) in fixtures.items()}
    tooltree=workspace/'test_tools' if synchronized else tree
    tooltree.mkdir(exist_ok=True)
    (tooltree/'BUILD.bazel').write_text('load("@rules_msbuild//tests/support:vstest.bzl", "vstest_tools")\nvstest_tools(name="tools",runner_package="//Vstest/packages:microsoft.testplatform.cli",runner_path="contentFiles/any/net9.0/vstest.console.dll",adapters='+json.dumps(adapters)+',visibility=["//visibility:public"])\n')
    if synchronized:
        (workspace/'sync.json').write_text(json.dumps(mappings,indent=2)+'\n')
        entries=list(mappings['tests'])
        authored='load("@rules_msbuild//msbuild:sync.bzl","msbuild_sync")\nmsbuild_sync(name="sync",projects='+json.dumps(entries)+',mappings="sync.json")\n'
        (workspace/'BUILD.bazel').write_text(authored)
        startup=[BAZEL,'--output_base='+str(folder/'base')]
        try:
            result=command(startup+['run','//:sync'],workspace,folder/'sync.log')
            assert result.returncode==0,(result.stdout+result.stderr)[-6000:]
        finally:
            subprocess.run(startup+['shutdown'],cwd=workspace,check=True)
        (workspace/'BUILD.bazel').write_text('load(":projects.generated.bzl","app_projects")\n'+authored+'app_projects()\n')
    return workspace


def run(folder, synchronized=False):
    workspace=setup(folder,synchronized)
    startup=[BAZEL,'--host_jvm_args=-Xmx768m','--output_base='+str(folder/'base'),'--ignore_all_rc_files']
    rows=[]
    try:
        for framework in ('Xunit','Nunit','Mstest'):
            target='//:Vstest_'+framework+'_'+framework+'_net10_0' if synchronized else '//Vstest/'+framework
            logs=workspace/('bazel-testlogs/Vstest_'+framework+'_'+framework+'_net10_0' if synchronized else 'bazel-testlogs/Vstest/'+framework+'/'+framework)
            for case,flags,count,success in [('pass',[],4,True),('filter',['--test_filter=FullyQualifiedName~Passes'],1,True),('failure',['--test_env=CASE=fail'],4,False),('empty',['--test_filter=FullyQualifiedName~Absent'],1,False)]:
                name=framework+'-'+case
                p=command(startup+['test',target,'--test_output=all','--strategy=MSBuildAssembly='+('local' if synchronized else 'worker'),'--worker_max_instances=MSBuildAssembly=1','--jobs=4','--build_event_json_file='+str(folder/(name+'.bep')),*flags],workspace,folder/(name+'.log'))
                assert (p.returncode==0)==success,(name,(p.stdout+p.stderr)[-4000:])
                if framework=='Xunit' and case=='pass':
                    assert (logs/'test.outputs/files/tests/logs/result.txt').read_text()=='retained'
                xml=logs/'test.xml'
                shutil.copyfile(xml,folder/(name+'.xml'));root=ET.parse(xml).getroot()
                assert len(root.findall('.//testcase'))==count,(name,ET.tostring(root))
                rows.append(dict(case=name,exit=p.returncode,tests=count,failures=len(root.findall('.//failure')),errors=len(root.findall('.//error')),skipped=len(root.findall('.//skipped'))));print(rows[-1],flush=True)
    finally:
        (folder/'vstest-results.json').write_text(json.dumps(rows,indent=2)+'\n')
        subprocess.run(startup+['shutdown'],cwd=workspace,check=True)


if __name__=='__main__':run(Path(sys.argv[1]).resolve(), '--sync' in sys.argv)
