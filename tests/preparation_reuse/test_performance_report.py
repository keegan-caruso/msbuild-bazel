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


class CalibrationGuardTests(unittest.TestCase):
    def test_output_inside_controller_rejected_before_creation(self):
        from unittest.mock import patch
        from probe_preparation_performance import probe, ROOT
        output = ROOT / 'must-not-create-calibration-output'
        with patch('pathlib.Path.mkdir') as mkdir:
            with self.assertRaisesRegex(ValueError, 'controller and evidence'):
                probe(Path('/private/tmp/separate-source'), [], output, 5, 'test')
            mkdir.assert_not_called()

    def test_changed_tools_cannot_complete_calibration(self):
        from contextlib import contextmanager
        import tempfile
        from unittest.mock import patch
        from probe_preparation_performance import probe
        import json

        @contextmanager
        def fresh(*args, **kwargs):
            yield dict(reused=False, discoveryExecuted=True, materializationExecuted=True, toolBuildsExecuted=True)

        @contextmanager
        def prepared(source, state, target, entries):
            reused = target.name != 'seed'
            yield dict(reused=reused, discoveryExecuted=not reused, materializationExecuted=not reused, toolBuildsExecuted=False)

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'evidence'
            with patch('probe_preparation_performance.tree_snapshot', return_value={'sha256': 'source'}), \
                 patch('probe_preparation_performance.tool_identity', side_effect=['before', 'stable', 'changed']), \
                 patch('probe_preparation_performance.subprocess.check_output', return_value='test'), \
                 patch('probe_preparation_performance.fresh_view', fresh), \
                 patch('probe_preparation_performance.prepared_view', prepared):
                with self.assertRaisesRegex(AssertionError, 'changed tools'):
                    probe(Path(directory) / 'source', [], output, 3, 'test')
            self.assertFalse(json.loads((output / 'report.json').read_text())['complete'])


if __name__ == '__main__':
    unittest.main()
