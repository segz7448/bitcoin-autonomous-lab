"""Short, bounded hashrate benchmark.

Measures header-hashing throughput for the hashlib (C/OpenSSL) path and,
briefly, the pure-Python reference path. Numbers describe only the machine
that ran the benchmark; they say nothing about outcomes on the live network.
"""

from __future__ import annotations

import hashlib
import struct
import time

from blockchain import sha256 as slow_sha


def bench_hashlib(seconds: float = 10.0) -> dict:
    prefix = b"\x00" * 76
    sha256 = hashlib.sha256
    start = time.monotonic()
    nonce = 0
    while time.monotonic() - start < seconds:
        sha256(sha256(prefix + struct.pack("<I", nonce)).digest()).digest()
        nonce += 1
    elapsed = time.monotonic() - start
    return {"hashes": nonce, "seconds": round(elapsed, 2),
            "hashrate_hs": round(nonce / elapsed, 1)}


def bench_pure_python(max_hashes: int = 2000) -> dict:
    prefix = b"\x00" * 76
    start = time.monotonic()
    for nonce in range(max_hashes):
        slow_sha.sha256d(prefix + struct.pack("<I", nonce))
    elapsed = time.monotonic() - start
    return {"hashes": max_hashes, "seconds": round(elapsed, 2),
            "hashrate_hs": round(max_hashes / elapsed, 1)}


def main() -> None:
    fast = bench_hashlib()
    print(f"hashlib sha256d : {fast['hashrate_hs']:,} H/s "
          f"({fast['hashes']:,} hashes in {fast['seconds']}s)")
    slow = bench_pure_python()
    print(f"pure-python     : {slow['hashrate_hs']:,} H/s "
          f"({slow['hashes']:,} hashes in {slow['seconds']}s)")
    ratio = fast["hashrate_hs"] / max(slow["hashrate_hs"], 1e-9)
    print(f"speed ratio     : {ratio:,.0f}x")


if __name__ == "__main__":
    main()
