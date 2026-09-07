"""Pure protocol checks for the R04 comparative measurement harness."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))

from probe_serilog_performance import (CASES, build_schedule, classify_bazel_actions,
                                       parse_msbuild_csc_count, parse_msbuild_target_visits,
                                       summarize_samples)


class SerilogPerformanceProtocol(unittest.TestCase):
    def test_schedule_interleaves_system_order_and_keeps_every_pair(self):
        schedule = build_schedule(3)
        self.assertEqual(len(schedule), 3 * len(CASES))
        for case in CASES:
            slots = [slot for slot in schedule if slot['case'] == case]
            self.assertEqual([slot['repetition'] for slot in slots], [1, 2, 3])
            self.assertEqual({tuple(slot['systems']) for slot in slots},
                             {('ordinary', 'bazel'), ('bazel', 'ordinary')})

    def test_compiler_count_uses_executed_csc_task_starts(self):
        log = '''Task "Csc" (TaskId:41)\nTarget "CoreCompile" skipped\nTask "Csc" (TaskId:73)\n'''
        self.assertEqual(parse_msbuild_csc_count(log), 2)

    def test_target_visits_are_retained_separately_from_compiler_count(self):
        log = '''Target Performance Summary:\n        1 ms  ResolveReferences  2 calls\n       12 ms  CoreCompile  1 calls\nTask Performance Summary:\n'''
        self.assertEqual(parse_msbuild_target_visits(log), [
            {'target': 'ResolveReferences', 'calls': 2},
            {'target': 'CoreCompile', 'calls': 1},
        ])

    def test_action_classifier_preserves_cache_and_runner_evidence(self):
        graph = {'nodes': [
            {'id': 'a' * 24, 'project': 'workspace/src/Serilog/Serilog.csproj'},
            {'id': 'b' * 24, 'project': 'workspace/test/Serilog.ApprovalTests/Serilog.ApprovalTests.csproj'},
        ]}
        records = [
            {'mnemonic': 'MsbuildProject', 'targetLabel': '//:node_' + 'a' * 24,
             'cacheHit': True, 'runner': 'disk cache hit'},
            {'mnemonic': 'TestRunner', 'targetLabel': '//:test_' + 'b' * 24,
             'cacheHit': False, 'runner': 'darwin-sandbox'},
        ]
        builds, tests = classify_bazel_actions(records, graph)
        self.assertEqual(builds[0]['project'], 'Serilog')
        self.assertTrue(builds[0]['cacheHit'])
        self.assertFalse(tests[0]['cacheHit'])

    def test_summary_reports_median_and_range_without_speedup(self):
        samples = []
        for value in (3.0, 1.0, 2.0):
            samples.append(dict(status='passed', case='fresh', system='ordinary',
                comparisonSeconds=value, fullWorkflowSeconds=value + 1,
                comparisonPeakAggregateRssBytes=100,
                phases={'build': {'wallSeconds': value}}))
        summary = summarize_samples(samples)
        metric = summary['fresh']['ordinary']['metrics']['comparisonSeconds']
        self.assertEqual(metric, {'median': 2.0, 'minimum': 1.0, 'maximum': 3.0})
        self.assertNotIn('speedup', summary['fresh']['ordinary'])


if __name__ == '__main__':
    unittest.main()
