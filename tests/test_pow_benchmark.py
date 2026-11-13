"""Benchmark module checks. Accuracy only: exact counts and internally consistent
timing. Absolute speed is never asserted (machine dependent)."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mining.pow import benchmark as b
from mining.pow.double_sha256 import double_sha256
from mining.pow.nonce_search import NonceSearcher
import hashlib


class TestBenchmark(unittest.TestCase):
    def test_measure_counts_and_rates_consistent(self):
        calls = []
        r = b.measure(lambda: [calls.append(1) for _ in range(1000)], 1000)
        self.assertEqual(len(calls), 1000)
        self.assertEqual(r["hashes"], 1000)
        self.assertGreater(r["wall_s"], 0)
        self.assertAlmostEqual(r["hashrate_hs"], 1000 / r["wall_s"], delta=1e-6 * r["hashrate_hs"])
        self.assertGreaterEqual(r["cpu_utilization"], 0)

    def test_hash_counts_are_exact_and_deterministic(self):
        out = b.run_all(fast_n=2000, pure_n=50, repeats=3)
        by = {r["name"].split(" (")[0] + r["name"][-8:]: r for r in out["results"]}
        for r in out["results"]:
            self.assertEqual(r["repeats"], 3)
            self.assertEqual(r["total_hashes"], 3 * r["hashes_per_run"])
            self.assertLessEqual(r["rate_min_hs"], r["rate_median_hs"])
            self.assertLessEqual(r["rate_median_hs"], r["rate_max_hs"])
        self.assertEqual([r["hashes_per_run"] for r in out["results"]], [2000, 2000, 2000, 50, 50])

    def test_benchmark_workload_matches_real_hashing(self):
        # The benchmarked operations are the real functions: same output as hashlib.
        h = b.BENCH_HEADER
        self.assertEqual(len(h), 80)
        self.assertEqual(double_sha256(h), hashlib.sha256(hashlib.sha256(h).digest()).digest())
        # Nonce-search benchmark path counts every nonce exactly once.
        r = NonceSearcher().search(h, 1, 0, 777)
        self.assertEqual(r.hashes_attempted, 777)

    def test_rate_scales_with_work(self):
        small = b.bench_double_pure(20, 1)["total_wall_s"]
        big = b.bench_double_pure(200, 1)["total_wall_s"]
        self.assertGreater(big, small)


if __name__ == "__main__":
    unittest.main()
