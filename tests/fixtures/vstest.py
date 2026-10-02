"""VSTest contract qualification with small xUnit, NUnit, and MSTest projects."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

from protocol import RULES, SDK, BAZEL, command, packages

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from fixture_sdk import sdk_declarations


def setup(folder):
    workspace=folder/'src'
    workspace.mkdir(parents=True, exist_ok=True)
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
        if name == 'Xunit':
            (dest/'input.txt').write_text('declared')
        project_file=dest/(name+'.csproj')
        project_file.write_text(project_file.read_text().replace('<TargetFramework>', '<AssemblyName>'+name+'.Tests</AssemblyName><TargetFramework>'))
        (dest/'settings.runsettings').write_text('<RunSettings><RunConfiguration><DotNetHostPath>/must-not-use-this-host/dotnet</DotNetHostPath><EnvironmentVariables><FROM_SETTINGS>declared</FROM_SETTINGS></EnvironmentVariables></RunConfiguration></RunSettings>')
    return workspace
