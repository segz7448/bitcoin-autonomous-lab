"""Repeatable throughput benchmarks (CPU only; no GPU).

Reproducibility: fixed input header, fixed nonce range, fixed hash counts
(not time-boxed), N repeats, and the median/min/max of the repeats is
reported. Hash COUNTS are exact and deterministic; elapsed time and rate
depend on the machine. CPU utilisation is process CPU time / wall time,
and memory is peak RSS (resource.getrusage, where available).

This module measures speed only. Correctness lives in the test suite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time

from .double_sha256 import double_sha256
from .nonce_search import NonceSearcher
from .sha256 import sha256

try:
    import resource
except ImportError:  # pragma: no cover - non-POSIX
    resource = None

# Deterministic benchmark header (arbitrary fixed bytes; target never hit).
BENCH_HEADER = bytes(i * 7 % 256 for i in range(80))


def _peak_rss_kb():
    if resource is None:
        return None
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss  # KiB on Linux


def measure(fn, hashes: int) -> dict:
    """Run fn() once; return exact hash count with wall/CPU time and rate."""
    wall0, cpu0 = time.perf_counter(), time.process_time()
    fn()
    wall, cpu = time.perf_counter() - wall0, time.process_time() - cpu0
    return {"hashes": hashes, "wall_s": wall, "cpu_s": cpu,
            "hashrate_hs": hashes / wall if wall > 0 else 0.0,
            "cpu_utilization": cpu / wall if wall > 0 else None}


def _summarize(name: str, runs: list) -> dict:
    rates = [r["hashrate_hs"] for r in runs]
    utils = [r["cpu_utilization"] for r in runs if r["cpu_utilization"] is not None]
    return {
        "name": name, "repeats": len(runs), "hashes_per_run": runs[0]["hashes"],
        "total_hashes": sum(r["hashes"] for r in runs),
        "total_wall_s": round(sum(r["wall_s"] for r in runs), 4),
        "rate_median_hs": round(statistics.median(rates), 1),
        "rate_min_hs": round(min(rates), 1), "rate_max_hs": round(max(rates), 1),
        "cpu_utilization_median": round(statistics.median(utils), 3) if utils else None,
        "peak_rss_kib": _peak_rss_kb(),
    }


def bench_sha256_hashlib(n: int, repeats: int) -> dict:
    data = BENCH_HEADER
    h = hashlib.sha256
    def run():
        for i in range(n):
            h(data).digest()
    return _summarize("sha256 (hashlib/OpenSSL, 80B)", [measure(run, n) for _ in range(repeats)])


def bench_double_hashlib(n: int, repeats: int) -> dict:
    data = BENCH_HEADER
    h = hashlib.sha256
    def run():
        for i in range(n):
            h(h(data).digest()).digest()
    return _summarize("double-sha256 (hashlib/OpenSSL, 80B)", [measure(run, n) for _ in range(repeats)])


def bench_sha256_pure(n: int, repeats: int) -> dict:
    data = BENCH_HEADER
    def run():
        for i in range(n):
            sha256(data)
    return _summarize("sha256 (pure Python reference, 80B)", [measure(run, n) for _ in range(repeats)])


def bench_double_pure(n: int, repeats: int) -> dict:
    data = BENCH_HEADER
    def run():
        for i in range(n):
            double_sha256(data)
    return _summarize("double-sha256 (pure Python reference, 80B)", [measure(run, n) for _ in range(repeats)])


def bench_nonce_search(n: int, repeats: int) -> dict:
    """Full nonce-engine loop (midstate + compare) over exactly n nonces; target=1 never hit."""
    def run():
        r = NonceSearcher().search(BENCH_HEADER, 1, 0, n)
        if r.hashes_attempted != n or r.status.value != "exhausted":
            raise RuntimeError("benchmark search did not cover exactly n nonces")
    return _summarize("nonce search engine (midstate, target compare)",
                      [measure(run, n) for _ in range(repeats)])


def run_all(fast_n: int = 200_000, pure_n: int = 3_000, repeats: int = 5) -> dict:
    return {
        "parameters": {"fast_hashes_per_run": fast_n, "pure_hashes_per_run": pure_n,
                       "repeats": repeats, "header_bytes": len(BENCH_HEADER)},
        "results": [bench_sha256_hashlib(fast_n, repeats), bench_double_hashlib(fast_n, repeats),
                    bench_nonce_search(fast_n, repeats),
                    bench_sha256_pure(pure_n, repeats), bench_double_pure(pure_n, repeats)],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="PoW engine benchmarks (CPU)")
    ap.add_argument("--fast-hashes", type=int, default=200_000)
    ap.add_argument("--pure-hashes", type=int, default=3_000)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    out = run_all(a.fast_hashes, a.pure_hashes, a.repeats)
    if a.json:
        print(json.dumps(out, indent=2))
        return
    for r in out["results"]:
        print(f"{r['name']:<48} median {r['rate_median_hs']:>12,.0f} H/s "
              f"(min {r['rate_min_hs']:,.0f}, max {r['rate_max_hs']:,.0f}) "
              f"total {r['total_hashes']:,} hashes, cpu {r['cpu_utilization_median']}, "
              f"peak RSS {r['peak_rss_kib']} KiB")


if __name__ == "__main__":
    main()
