import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from probe_serilog_api import compare


@unittest.skipUnless(all(os.environ.get(name) for name in
    ('RULES_MSBUILD_SERILOG_SOURCE', 'RULES_MSBUILD_SERILOG_PACKAGES', 'RULES_MSBUILD_SERILOG_ASSEMBLY', 'RULES_MSBUILD_DOTNET_ROOT')),
    'requires acquired pinned source, packages, ordinary assembly and SDK')
class ApiOracleAcceptance(unittest.TestCase):
    def test_ordinary_public_api_and_incompatible_assembly_control(self):
        evidence = Path(tempfile.mkdtemp(prefix='serilog-api-oracle-')).resolve()
        args = (os.environ['RULES_MSBUILD_SERILOG_SOURCE'], os.environ['RULES_MSBUILD_SERILOG_PACKAGES'])
        sdk = os.environ['RULES_MSBUILD_DOTNET_ROOT']
        report = compare(*args, os.environ['RULES_MSBUILD_SERILOG_ASSEMBLY'], evidence / 'ordinary', sdk)
        self.assertTrue(report['passed'])
        self.assertFalse(report['upstreamTestProjectExecuted'])
        self.assertEqual(len(report['packageArchiveSha256']), 3)
        # The oracle executable has a different public surface from Serilog.
        wrong = evidence / 'ordinary/helper/bin/Release/net10.0/SerilogApiOracle.dll'
        negative = compare(*args, wrong, evidence / 'incompatible', sdk)
        self.assertFalse(negative['passed'])
        self.assertTrue((evidence / 'incompatible/public-api.diff').read_text())
        self.assertFalse(json.loads((evidence / 'incompatible/report.json').read_text())['passed'])
        print('Public API oracle evidence: ' + str(evidence), flush=True)
