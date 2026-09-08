"""Opt-in pinned-checkout ordinary oracle; acquisition stays outside this test."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest

from probe import probe


@unittest.skipUnless(os.environ.get('RULES_MSBUILD_SERILOG_SOURCE') and os.environ.get('RULES_MSBUILD_SERILOG_PACKAGES'),
                     'set RULES_MSBUILD_SERILOG_SOURCE and RULES_MSBUILD_SERILOG_PACKAGES to the pinned acquired pilot')
class SerilogInputs(unittest.TestCase):
    def test_selected_inner_required_inputs(self):
        output = Path(tempfile.mkdtemp(prefix='serilog-inputs-')) / 'probe'
        report = probe(os.environ['RULES_MSBUILD_SERILOG_SOURCE'], os.environ['RULES_MSBUILD_SERILOG_PACKAGES'], output)
        self.assertEqual(report['sdkVersion'], '10.0.400')
        self.assertTrue(report['sourceDeclarationPreserved'])
        self.assertIn('netstandard2.0', report['properties']['TargetFrameworks'])
        self.assertEqual(report['properties']['TargetFramework'], 'net10.0')
        self.assertEqual(report['selectedPackages'], ['Microsoft.NET.ILLink.Tasks/10.0.11', 'PolySharp/1.15.0'])
        self.assertEqual(len(report['analyzers']), 11)
        self.assertTrue(any(p['Identity'].endswith('/PolySharp.SourceGenerators.dll') for p in report['analyzers']))
        self.assertEqual(sorted(Path(p).name for p in report['generatedSources']),
            ['System.Runtime.CompilerServices.IsExternalInit.g.cs', 'System.Runtime.CompilerServices.RequiresLocationAttribute.g.cs'])
        self.assertEqual([Path(p).name for p in report['generatorExcludeOptionSources']], ['System.Runtime.CompilerServices.RequiresLocationAttribute.g.cs'])
        self.assertEqual(report['additionalFiles'], [])
        self.assertEqual(report['observation']['token'], '24C2F752A8E58A10')
        self.assertEqual(report['observation']['resources'], ['ILLink.Substitutions.xml'])
        resource = output / 'source/src/Serilog/ILLink.Substitutions.xml'
        self.assertEqual(report['observation']['resourceHash'], hashlib.sha256(resource.read_bytes()).hexdigest().upper())
        self.assertEqual(report['observation']['logging'], 'Hello "Ada"')
        self.assertEqual(report['missingKeyObservation']['token'], '')
        self.assertEqual(report['missingKeyObservation']['logging'], report['observation']['logging'])
        print('Serilog input evidence: ' + str(output), flush=True)


if __name__ == '__main__':
    unittest.main()
