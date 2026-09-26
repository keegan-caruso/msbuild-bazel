"""Qualification parity must preserve case counts and failed outcomes."""
from collections import Counter
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'explicit_msbuild/runtime'))
from case_names import normalized, shuffled


class CaseNamesTests(unittest.TestCase):
    def test_only_reviewed_parameter_displays_are_normalized(self):
        method = sorted(shuffled)[0]
        a = Counter({(method + '(source: first)', 'Passed'): 2})
        b = Counter({(method + '(source: second)', 'Passed'): 2})
        self.assertEqual(normalized(a), normalized(b))
        self.assertNotEqual(normalized(a), normalized(Counter({(method + '(source: second)', 'Passed'): 1})))
        self.assertNotEqual(normalized(a), normalized(Counter({(method + '(source: second)', 'Failed'): 2})))
        self.assertNotEqual(normalized(Counter({('Other(x: 1)', 'Passed'): 1})), normalized(Counter({('Other(x: 2)', 'Passed'): 1})))
