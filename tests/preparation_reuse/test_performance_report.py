import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from probe_preparation_performance import summarize


class CalibrationReportTests(unittest.TestCase):
    def test_failed_samples_do_not_silently_become_successful_timings(self):
        samples = [dict(mode='fresh', status='passed', seconds=value) for value in (2, 4, 9)]
        samples += [dict(mode='reuse', status='passed', seconds=value) for value in (1, 2, 3)]
        samples += [dict(mode='reuse', status='failed', seconds=100)]
        summary = summarize(samples)
        self.assertEqual(summary['fresh']['median'], 4)
        self.assertEqual(summary['reuse']['count'], 3)
        self.assertEqual(summary['medianReuseToFreshRatio'], 0.5)
        self.assertNotIn('performanceQualified', summary)

    def test_missing_comparator_produces_no_ratio(self):
        summary = summarize([dict(mode='fresh', status='passed', seconds=3)])
        self.assertNotIn('medianReuseToFreshRatio', summary)


if __name__ == '__main__':
    unittest.main()
