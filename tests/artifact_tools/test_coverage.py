"""LCOV conversion policy controls; real instrumentation lives in graph/protocols.py."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SDK = Path(os.environ['RULES_MSBUILD_DOTNET_ROOT'])
DOTNET = SDK / ('dotnet.exe' if os.name == 'nt' else 'dotnet')
RUNNER = ROOT / 'tools/ArtifactTools/bin/Release/net11.0/ArtifactTools.dll'


class CoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='coverage-policy-')
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(cls.temporary.name)
        (cls.root / 'Reporter.csproj').write_text('<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType><TargetFramework>net11.0</TargetFramework><ImplicitUsings>enable</ImplicitUsings></PropertyGroup></Project>')
        (cls.root / 'Program.cs').write_text('''
var output = args[Array.IndexOf(args, "--results-directory") + 1];
var count = Environment.GetEnvironmentVariable("LCOV_POLICY_TEST_COUNT") ?? "0";
var results = count == "1" ? "<Results><UnitTestResult testName='policy' outcome='Passed'/></Results>" : "";
File.WriteAllText(Path.Combine(output, "results.trx"), "<TestRun xmlns='http://microsoft.com/schemas/VisualStudio/TeamTest/2010'>" + results + "<ResultSummary outcome='Completed'><Counters total='" + count + "'/></ResultSummary></TestRun>");
File.Copy(Environment.GetEnvironmentVariable("LCOV_POLICY_FIXTURE")!, Path.Combine(output, "fixture.info"));
''')
        result = subprocess.run([str(DOTNET), 'build', str(cls.root / 'Reporter.csproj'), '-c', 'Release',
            '--disable-build-servers', '-p:NuGetAudit=false', '-p:RestoreSources=' + str(cls.root)], capture_output=True, text=True)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

    def invoke(self, lcov, *, coverage=True, collector='coverlet', success=True, test_count=0):
        with tempfile.TemporaryDirectory(prefix='coverage-record-') as temporary:
            folder = Path(temporary)
            payload = folder / 'fixture.info'
            payload.write_text(lcov)
            manifest = folder / 'runfiles.manifest'
            def entry(key, path):
                return ' ' + key + ' ' + str(path.resolve()).replace('\\', '\\b').replace('\n', '\\n') + '\n'
            manifest.write_bytes((entry('app', self.root / 'bin/Release/net11.0') + entry('host', SDK)).encode())
            request = folder / 'request.json'
            request.write_text(json.dumps(dict(entry='app', assembly='Reporter', data=[],
                runtimeHost=dict(directory='host', entryPoint=DOTNET.name),
                testOptions=dict(protocol='mtp', allowEmpty=True, coverage=collector,
                                 coverageSources={'Code.cs': 'src/Code.cs'}))))
            output = folder / 'coverage.dat'
            env = dict(os.environ, RULES_MSBUILD_RUNFILES=str(manifest), LCOV_POLICY_FIXTURE=str(payload), LCOV_POLICY_TEST_COUNT=str(test_count))
            env.pop('COVERAGE_OUTPUT_FILE', None)
            if coverage:
                output.write_text('stale report')
                env['COVERAGE_OUTPUT_FILE'] = str(output)
            result = subprocess.run([str(DOTNET), str(RUNNER), 'test-protocol', str(request)], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
            return output.read_text() if output.exists() else None, result.stdout + result.stderr

    def test_normalizes_only_declared_sources(self):
        record = 'SF:/_/workspace/Code.cs\nDA:2,3\nend_of_record\n\n'
        ignored = 'SF:/ambient/Host.cs\nDA:8,9\nend_of_record\n'
        output, _ = self.invoke(ignored + record)
        self.assertEqual(output, 'SF:src/Code.cs\nDA:2,3\nend_of_record\n')

    def test_rejects_incomplete_or_uninstrumented_records(self):
        for record, error in [('SF:/_/workspace/Code.cs\nDA:2,3\n', 'Incomplete LCOV'),
                              ('SF:/_/workspace/Code.cs\nend_of_record\n', 'no instrumented lines'),
                              ('SF:/_/workspace/Code.cs\nDA:2,-1\nend_of_record\n', 'Invalid LCOV line counter')]:
            with self.subTest(record=record):
                output, log = self.invoke(record, success=False)
                self.assertIn(error, log)
                self.assertEqual(output, '')

    def test_missing_coverage_is_allowed_only_for_empty_results(self):
        output, _ = self.invoke('', test_count=0)
        self.assertEqual(output, '')
        output, log = self.invoke('', test_count=1, success=False)
        self.assertEqual(output, '')
        self.assertIn('no LCOV coverage for declared graph sources', log)

    def test_requires_declared_collector_configuration(self):
        _, log = self.invoke('', collector='', success=False)
        self.assertIn('requires test_coverage', log)

    def test_ordinary_test_does_not_collect_coverage(self):
        output, _ = self.invoke('unparsed fixture', coverage=False)
        self.assertIsNone(output)
