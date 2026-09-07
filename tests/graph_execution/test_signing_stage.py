"""Native dependency evaluation keeps a conditionally enabled signing key."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import probe_graph_execution


@unittest.skipUnless(os.environ.get('SPIKE_SERILOG_SOURCE'), 'requires acquired pinned Serilog key fixture')
class SigningStageAcceptance(unittest.TestCase):
    def test_dependency_key_preserves_conditional_signing(self):
        source = Path(os.environ['SPIKE_SERILOG_SOURCE'])
        self.assertEqual(subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip(),
                         '49b5339ce85385dc52d4d8e8f2b8308becf23506')
        original = probe_graph_execution.write_fixture
        def fixture(workspace):
            original(workspace)
            folder = workspace / 'src/Shared'
            (folder / 'key.snk').write_bytes((source / 'assets/Serilog.snk').read_bytes())
            project = folder / 'Shared.csproj'
            project.write_text(project.read_text().replace('</Project>', '''<PropertyGroup><SignAssembly Condition="Exists('$(MSBuildThisFileDirectory)key.snk')">true</SignAssembly><AssemblyOriginatorKeyFile>key.snk</AssemblyOriginatorKeyFile></PropertyGroup><Target Name="AssertDependencySigning" BeforeTargets="GetTargetFrameworks"><Error Condition="'$(SignAssembly)' != 'true'" Text="dependency signing state changed" /></Target></Project>'''))
        output = Path(tempfile.mkdtemp(prefix='graph-signing-stage-')) / 'probe'
        with patch.object(probe_graph_execution, 'write_fixture', fixture):
            report = probe_graph_execution.probe(output)
        self.assertEqual(report['output'], 'shared-v1:left|shared-v1:right')
        self.assertEqual(report['output'], report['baselineOutput'])
        self.assertTrue(report['preparationWorkspaceAbsent'])
        self.assertEqual(set(report['actions']['src/App/App.csproj']['replayHits']), {'Shared', 'Left', 'Right'})
        print('Signing dependency evidence: ' + str(output), flush=True)


if __name__ == '__main__':
    unittest.main()
