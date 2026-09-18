import time
from pathlib import Path
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from probe_http_cache import Bandwidth, CacheServer
from portable_cache import fetch, sha


class BandwidthTests(unittest.TestCase):
    def test_bandwidth_is_shared(self):
        budget = Bandwidth(8)  # 1 MB/s total, not per concurrent transfer.
        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=4) as pool: list(pool.map(budget.wait, [100000]*4))
        self.assertGreaterEqual(time.perf_counter() - start, .39)
        self.assertLess(time.perf_counter() - start, 2)

    def test_http_transfers_share_budget(self):
        data = b'x' * 100000; key = sha(data)
        with CacheServer(download_mbps=8) as server:
            server.data['/native/cas/' + key] = data
            start = time.perf_counter()
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(fetch, [server.url + '/native/cas/' + key] * 4))
            self.assertEqual(results, [data] * 4)
            self.assertGreaterEqual(time.perf_counter() - start, .39)
        self.assertEqual(server.totals()['downloadBytes'], 400000)

    def test_invalid_profiles_reject(self):
        for value in (-1, float('inf'), float('nan')):
            with self.assertRaises(ValueError): Bandwidth(value)
            with self.assertRaises(ValueError): CacheServer(delay_ms=value)
