#!/usr/bin/env python3
"""TASK 003 milestone: independent SHA-256 Proof-of-Work engine, live on regtest.

Every line is executed, not asserted from a fixture alone: hashes are
recomputed by the independent engine and compared with Bitcoin Core's
replies on a real regtest node (plus real mainnet headers). Non-zero exit
on any failure.

Usage:
  BAL_BITCOIND=/path/to/bitcoind python3 scripts/milestone_003.py
"""
from __future__ import annotations

import hashlib
import os
import shutil
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mining.pow import benchmark
from mining.pow.block_header import BlockHeader
from mining.pow.core_verify import (mine_block_with_engine, tamper_to_invalid_pow, verify_chain)
from mining.pow.double_sha256 import double_sha256, double_sha256_hex
from mining.pow.nonce_search import NONCE_SPACE, NonceSearcher, SearchStatus
from mining.pow.sha256 import sha256_hex
from mining.pow.target import (BITS_MAINNET_LIMIT, POW_LIMIT_MAINNET, POW_LIMIT_REGTEST,
                               bits_to_target, decode_compact)
from mining.pow.validator import validate_header
from node.node_manager import NodeConfig, NodeManager
from tests.pow_fixtures import MAINNET

OK = True


def check(label, cond, detail=""):
    global OK
    OK &= bool(cond)
    print(f"  [{'PASS' if cond else 'FAIL'}] {label}" + (f" - {detail}" if detail else ""))


def main() -> int:
    print("== 1. SHA-256 (FIPS 180-4 vectors) and double SHA-256 ==")
    check("SHA256('abc')", sha256_hex(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
          sha256_hex(b"abc")[:16] + "...")
    check("SHA256('') ", sha256_hex(b"") == hashlib.sha256(b"").hexdigest())
    check("SHA256(1,000,000 x 'a')", sha256_hex(b"a" * 1_000_000) ==
          "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0")
    check("SHA256d('hello')", double_sha256_hex(b"hello") ==
          "9595c9df90075148eb06860365df33584b75bff782a510c6cd4883a419833d50")
    check("own SHA-256 == hashlib for lengths 0..300", all(
        sha256_hex(bytes((i * 3) % 256 for i in range(n)))
        == hashlib.sha256(bytes((i * 3) % 256 for i in range(n))).hexdigest() for n in range(301)))

    print("== 2. Real MAINNET headers: serialize / hash / PoW ==")
    for f in MAINNET:
        raw = bytes.fromhex(f["header"])
        h = BlockHeader.deserialize(raw)
        v = validate_header(h)
        check(f"mainnet block {f['height']}", h.serialize() == raw and h.hash_display() == f["hash"] and v.valid,
              f"{h.hash_display()[:24]}... nonce={h.nonce}")

    print("== 3. nBits decoding (Core rules) ==")
    t = decode_compact(BITS_MAINNET_LIMIT)
    check("0x1d00ffff -> 00000000ffff0000...", t.value == POW_LIMIT_MAINNET and t.valid)
    check("0x04923456 negative", decode_compact(0x04923456).negative)
    check("0xff123456 overflow", decode_compact(0xFF123456).overflow)
    check("0x00000000 zero", decode_compact(0).zero and not decode_compact(0).valid)

    print("== 4. Live Bitcoin Core regtest ==")
    datadir = tempfile.mkdtemp(prefix="bal-ms003-")
    cfg = NodeConfig.from_env()
    cfg.datadir, cfg.rpc_port = datadir, 18448
    manager = NodeManager(cfg)
    rpc = manager.start()
    try:
        info = rpc.get_blockchain_info()
        print(f"  node: chain={info['chain']} height={info['blocks']} (Bitcoin Core regtest, fresh datadir)")
        rpc.create_wallet("bal")
        addr = rpc.get_new_address()
        script = bytes.fromhex(rpc.get_address_info(addr)["scriptPubKey"])
        rpc.generate_to_address(6, addr)
        report = verify_chain(rpc)
        print(f"  {'height':>6}  {'core hash (display)':<66}{'engine==core':<13}{'80B==core hex':<14}{'PoW':<5}")
        for row in report["blocks"]:
            c = row["checks"]
            print(f"  {row['height']:>6}  {row['hash']}  {str(c['hash_matches_core']):<12} "
                  f"{str(c['serialization_matches_core_hex']):<13} {'ok' if c['pow_valid'] else 'BAD'}")
        names = sorted({k for r in report["blocks"] for k in r["checks"]})
        for n in names:
            check(f"all {len(report['blocks'])} blocks: {n}",
                  all(r["checks"].get(n, True) for r in report["blocks"]))

        out = mine_block_with_engine(rpc, script, POW_LIMIT_REGTEST)
        check("engine mined a block that Core accepted", out["accepted_and_matches"],
              f"height={out['height']} nonce={out['nonce']} tries={out['hashes_attempted']} "
              f"hash={out['engine_hash'][:20]}...")

        tip = rpc.get_best_block_hash()
        bad_hex, ours = tamper_to_invalid_pow(rpc.call("getblock", tip, 0), POW_LIMIT_REGTEST)
        core_says = rpc.submit_block(bad_hex)
        check("invalid nonce: engine says high-hash, Core says the same", ours["reason"] == "high-hash" == core_says,
              f"engine={ours['reason']} core={core_says}")
        check("chain tip unchanged after rejected block", rpc.get_best_block_hash() == tip)
    finally:
        manager.stop()
        shutil.rmtree(datadir, ignore_errors=True)

    print("== 5. Nonce engine behaviour ==")
    hdr = BlockHeader(0x20000000, bytes(32), bytes(range(32)), 1_700_000_000, 0x1F00FFFF, 0).serialize()
    r = NonceSearcher().search_bits(hdr, POW_LIMIT_REGTEST)
    solved = BlockHeader.deserialize(hdr).with_nonce(r.nonce)
    check("difficulty-target search finds valid PoW (nBits 0x1f00ffff)", r.found and validate_header(
        solved, POW_LIMIT_REGTEST).valid, f"nonce={r.nonce} hashes={r.hashes_attempted} "
        f"{r.hashrate:,.0f} H/s hash={r.hash_display[:20]}...")
    ex = NonceSearcher().search(hdr, 1, NONCE_SPACE - 1000, NONCE_SPACE)
    check("nonce-space exhaustion reported, no wrap", ex.status is SearchStatus.EXHAUSTED
          and ex.hashes_attempted == 1000, f"hashes={ex.hashes_attempted} next={ex.next_nonce}")
    s = NonceSearcher()
    threading.Timer(0.3, s.stop).start()
    it = s.search(hdr, 1)
    check("graceful interrupt", it.status is SearchStatus.INTERRUPTED, f"stopped after {it.hashes_attempted:,} hashes, "
          f"resume at nonce {it.next_nonce}")

    print("== 6. Benchmarks (CPU, 3 repeats, exact hash counts) ==")
    res = benchmark.run_all(fast_n=200_000, pure_n=2_000, repeats=3)
    print(f"  python {res['environment']['python']} {res['environment']['machine']} cpus={res['environment']['cpu_count']}")
    for b in res["results"]:
        print(f"  {b['name']:<48} {b['rate_median_hs']:>12,.0f} H/s median  "
              f"(total {b['total_hashes']:,} hashes, cpu {b['cpu_utilization_median']}, rss {b['peak_rss_kib']} KiB)")

    print("MILESTONE RESULT: " + ("ALL CHECKS PASSED" if OK else "FAILURES"))
    return 0 if OK else 1


if __name__ == "__main__":
    sys.exit(main())
