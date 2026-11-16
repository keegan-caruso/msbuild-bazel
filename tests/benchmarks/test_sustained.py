"""Reject invalid tail summaries and retain failed resource observations."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from benchmarks.resources import GuestMemory, allocated_bytes
from benchmarks.sustained import percentiles


class Sustained(unittest.TestCase):
    def test_tail_requires_valid_complete_series(self):
        for values in [[1, 2, 3, 4], [1, 2, 3, 4, float('nan')], [1, 2, 3, 4, -1]]:
            with self.assertRaises(ValueError):
                percentiles(values)
        result = percentiles([5, 1, 4, 2, 3])
        self.assertEqual(result['p50Seconds'], 3)
        self.assertEqual(result['p95Seconds'], 5)

    @unittest.skipUnless(sys.platform == 'linux', 'Linux guest memory sampling')
    def test_sampler_stops_on_failed_workload(self):
        with self.assertRaisesRegex(RuntimeError, 'workload failure'):
            with GuestMemory() as sampler:
                raise RuntimeError('workload failure')
        self.assertFalse(sampler.thread.is_alive())
        self.assertGreater(sampler.summary()['minimumAvailableKiB'], 0)

    def test_owned_disk_count_ignores_missing_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root/'data').write_bytes(b'x'*16384)
            self.assertGreaterEqual(allocated_bytes([root, root/'missing']), 16384)


if __name__ == '__main__':
    unittest.main()
