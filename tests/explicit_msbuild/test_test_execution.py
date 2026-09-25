"""Failure controls for the test-process/report boundary without framework dependencies."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ.get('RULES_MSBUILD_DOTNET_ROOT', ROOT/'.tools/dotnet'))


class TestExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        (cls.root/'App.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><TargetFramework>net10.0</TargetFramework><OutputType>Exe</OutputType></PropertyGroup></Project>')
        (cls.root/'Program.cs').write_text('''using System; using System.IO; using System.Linq; using System.Threading;
var output=args[Array.IndexOf(args,"--results-directory")+1];
var mode=Environment.GetEnvironmentVariable("MODE");
Console.WriteLine("started");
if(mode=="hang") Thread.Sleep(120000);
if(mode=="cwd" && Path.GetFileName(Directory.GetCurrentDirectory())!="tests") throw new Exception("wrong cwd");
if(mode=="missing") return 0;
var xml=File.ReadAllText("input.trx");
File.WriteAllText(Path.Combine(output,"results.trx"),xml);
return mode=="nonzero" ? 17 : 0;
''')
        p=subprocess.run([str(SDK/'dotnet'),'build',str(cls.root/'App.csproj'),'-c','Release','-p:NuGetAudit=false'],capture_output=True,text=True)
        assert p.returncode==0,p.stdout+p.stderr

    @classmethod
    def tearDownClass(cls): cls.directory.cleanup()

    def launch(self, trx, mode='', allow_empty=False, cancel=False, settings_output=None, working_directory=None):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'input.trx').write_text(trx)
            (root/'settings.json').write_text('{}')
            (root/'launch.json').write_text(json.dumps(dict(entry='bin/Release/net10.0',dependencies=[],assembly='App',test=True,data=[dict(source='input.trx',path=(working_directory+'/' if working_directory else '')+'input.trx'),dict(source='settings.json',path='settings.json')],testOptions=dict(protocol='mtp',allowEmpty=allow_empty,settingsOutput=settings_output,workingDirectory=working_directory))))
            # Use a runfiles root containing the fake app and declared report payload.
            import shutil
            shutil.copytree(self.root/'bin',root/'bin')
            for name in ('.rules-msbuild-packages.json','.rules-msbuild-package-files.json'):
                (root/'bin/Release/net10.0'/name).write_text('{}')
            env=dict(os.environ,RULES_MSBUILD_RUNFILES=str(root),XML_OUTPUT_FILE=str(root/'test.xml'),TEST_TMPDIR=str(root/'tmp'),TEST_UNDECLARED_OUTPUTS_DIR=str(root/'outputs'),MODE=mode)
            env.pop('TESTBRIDGE_TEST_ONLY',None)
            p=subprocess.Popen([str(SDK/'dotnet'),str(ROOT/'tools/ExplicitBuild/bin/Release/net10.0/ExplicitBuild.dll'),'run',str(root/'launch.json')],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            if cancel:
                self.assertEqual(p.stdout.readline().strip(),'started')
                p.send_signal(signal.SIGTERM)
            stdout,stderr=p.communicate(timeout=15)
            return p.returncode,ET.parse(root/'test.xml').getroot(),stderr

    @staticmethod
    def report(results='', outcome='Completed'):
        return '<TestRun xmlns="http://microsoft.com/schemas/VisualStudio/TeamTest/2010"><Results>'+results+'</Results><ResultSummary outcome="'+outcome+'"/></TestRun>'

    def test_generated_settings_must_exist(self):
        trx=self.report('<UnitTestResult testName="passes" outcome="Passed"/>')
        code,xml,_=self.launch(trx,settings_output='settings.json')
        self.assertEqual(code,0)
        code,xml,_=self.launch(trx,settings_output='absent.json')
        self.assertNotEqual(code,0)
        self.assertIn('Missing declared test settings',xml.find('.//error').get('message'))

    def test_relative_working_directory_preserves_settings_and_reporting(self):
        trx=self.report('<UnitTestResult testName="passes" outcome="Passed"/>')
        code,xml,_=self.launch(trx,mode='cwd',settings_output='settings.json',working_directory='tests')
        self.assertEqual(code,0)
        self.assertEqual(len(xml.findall('.//testcase')),1)

    def test_missing_and_malformed_reports_fail(self):
        for mode,trx in [('missing',''),('', '<broken'),('', '<TestRun/>')]:
            with self.subTest(mode=mode,trx=trx):
                code,xml,_=self.launch(trx,mode)
                self.assertNotEqual(code,0);self.assertEqual(len(xml.findall('.//error')),1)

    def test_report_failure_cannot_be_hidden_by_zero_exit(self):
        code,xml,_=self.launch(self.report('<UnitTestResult testName="fails" outcome="Failed"><Output><ErrorInfo><Message>assert &amp; fail</Message></ErrorInfo></Output></UnitTestResult>'))
        self.assertNotEqual(code,0);self.assertEqual(xml.find('.//failure').get('message'),'assert & fail')

    def test_nonzero_exit_cannot_be_hidden_by_passing_report(self):
        code,xml,_=self.launch(self.report('<UnitTestResult testName="passes" outcome="Passed"/>'),'nonzero')
        self.assertEqual(code,17);self.assertEqual(len(xml.findall('.//error')),1)

    def test_incomplete_report_cannot_pass(self):
        trx=self.report('<UnitTestResult testName="passes" outcome="Passed"/>').replace('/></TestRun>', '><Counters total="2"/></ResultSummary></TestRun>')
        code,xml,_=self.launch(trx)
        self.assertNotEqual(code,0);self.assertEqual(len(xml.findall('.//error')),1)

    def test_empty_policy(self):
        for allow in (False,True):
            code,xml,_=self.launch(self.report(),allow_empty=allow)
            self.assertEqual(code==0,allow)

    def test_cancelled_process_fails(self):
        code,xml,_=self.launch('',mode='hang',cancel=True)
        self.assertNotEqual(code,0);self.assertIn('cancelled',xml.find('.//error').get('message'))

    def test_xml_external_entities_are_rejected(self):
        code,xml,_=self.launch('<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><TestRun>&e;</TestRun>')
        self.assertNotEqual(code,0);self.assertEqual(len(xml.findall('.//error')),1)
