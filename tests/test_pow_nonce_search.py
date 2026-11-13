"""Nonce engine: success, exact accounting, exhaustion, interruption, extra-nonce."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import signal, threading, time

from mining.pow.block_header import BlockHeader
from mining.pow.double_sha256 import double_sha256
from mining.pow.nonce_search import (NONCE_SPACE, NonceSearcher, SearchStatus, graceful_shutdown)
from mining.pow.target import (BITS_REGTEST_LIMIT, POW_LIMIT_MAINNET,
                               POW_LIMIT_REGTEST, check_proof_of_work, hash_to_int)
from mining.pow.validator import validate_header
from tests.pow_fixtures import GENESIS, MAINNET


def template(bits=BITS_REGTEST_LIMIT, seed=0):
    return BlockHeader(0x20000000, seed.to_bytes(32, 'big'), (seed + 1).to_bytes(32, 'big'),
                       1_700_000_000, bits, 0).serialize()


class TestSearch(unittest.TestCase):
    def test_finds_real_mainnet_nonce_in_small_window(self):
        # Genesis nonce 2083236893: search a window around it at the real target.
        raw = bytes.fromhex(GENESIS["header"])
        winner = 2083236893
        r = NonceSearcher().search_bits(raw[:76] + bytes(4), POW_LIMIT_MAINNET,
                                        start_nonce=winner - 500, end_nonce=winner + 500)
        self.assertTrue(r.found)
        self.assertEqual(r.nonce, winner)
        self.assertEqual(r.hash_display, GENESIS["hash"])
        self.assertEqual(r.hashes_attempted, 501)          # exact accounting: 500 misses + the hit

    def test_real_blocks_have_a_valid_nonce_found_by_engine(self):
        for f in MAINNET[1:3]:   # blocks 1 and 170 (difficulty 1)
            raw = bytes.fromhex(f["header"])
            true_nonce = int.from_bytes(raw[76:], "little")
            r = NonceSearcher().search_bits(raw[:76] + bytes(4), POW_LIMIT_MAINNET,
                                            start_nonce=true_nonce - 20, end_nonce=true_nonce + 20)
            self.assertTrue(r.found, f["height"])
            self.assertEqual(r.hash_display, f["hash"])

    def test_winner_validates_and_matches_plain_hash(self):
        hdr = template()
        r = NonceSearcher().search_bits(hdr, POW_LIMIT_REGTEST)
        self.assertTrue(r.found)
        solved = BlockHeader.deserialize(hdr).with_nonce(r.nonce)
        self.assertEqual(r.digest, double_sha256(solved.serialize()))   # midstate == plain hashing
        self.assertTrue(validate_header(solved, POW_LIMIT_REGTEST).valid)
        self.assertTrue(check_proof_of_work(r.digest, BITS_REGTEST_LIMIT, POW_LIMIT_REGTEST))

    def test_first_winner_is_lowest_nonce(self):
        hdr = template(seed=7)
        r = NonceSearcher().search_bits(hdr, POW_LIMIT_REGTEST)
        base = BlockHeader.deserialize(hdr)
        for n in range(r.nonce):
            self.assertFalse(validate_header(base.with_nonce(n), POW_LIMIT_REGTEST).valid, n)

    def test_hashes_attempted_exact_on_limit_and_resume(self):
        hdr = template()
        s = NonceSearcher(check_interval=10)
        r = s.search(hdr, 1, 0, NONCE_SPACE, max_hashes=1234)   # target 1: unreachable
        self.assertEqual(r.status, SearchStatus.LIMIT)
        self.assertEqual((r.hashes_attempted, r.next_nonce), (1234, 1234))
        r2 = s.search(hdr, 1, r.next_nonce, r.next_nonce + 100)
        self.assertEqual((r2.status, r2.start_nonce, r2.hashes_attempted), (SearchStatus.EXHAUSTED, 1234, 100))

    def test_nonce_space_exhaustion_does_not_wrap(self):
        hdr = template()
        r = NonceSearcher().search(hdr, 1, NONCE_SPACE - 1000, NONCE_SPACE)
        self.assertEqual(r.status, SearchStatus.EXHAUSTED)
        self.assertEqual(r.hashes_attempted, 1000)          # not 1001+, no wrap to nonce 0
        self.assertEqual(r.next_nonce, NONCE_SPACE)
        self.assertIsNone(r.nonce)
        self.assertIsNone(r.hash_display)
        # Boundary nonce 0xFFFFFFFF is actually tried.
        last = BlockHeader.deserialize(hdr).with_nonce(0xFFFFFFFF)
        tgt = hash_to_int(last.hash())
        r = NonceSearcher().search(hdr, tgt, NONCE_SPACE - 1, NONCE_SPACE)
        self.assertTrue(r.found and r.nonce == 0xFFFFFFFF)
        # Empty range is immediately exhausted.
        r = NonceSearcher().search(hdr, 1, 5, 5)
        self.assertEqual((r.status, r.hashes_attempted), (SearchStatus.EXHAUSTED, 0))

    def test_input_validation(self):
        s = NonceSearcher()
        hdr = template()
        for bad in (hdr[:79], hdr + b"\x00", b"", bytes(76)):
            with self.assertRaises(ValueError):
                s.search(bad, 1)
        for tgt in (0, -1, 2 ** 256):
            with self.assertRaises(ValueError):
                s.search(hdr, tgt)
        for a, b in ((-1, 5), (5, 4), (0, NONCE_SPACE + 1)):
            with self.assertRaises(ValueError):
                s.search(hdr, 1, a, b)
        with self.assertRaises(ValueError):
            NonceSearcher(check_interval=0)

    def test_search_bits_rejects_invalid_targets(self):
        s = NonceSearcher()
        for bits in (0, 0x01FEDCBA, 0xFF123456, 0x1E00FFFF):   # zero, negative, overflow, above mainnet limit
            with self.subTest(bits=hex(bits)):
                with self.assertRaises(ValueError):
                    s.search_bits(template(bits=bits), POW_LIMIT_MAINNET, max_hashes=10)

    def test_max_seconds_limit(self):
        clock = iter(x * 0.5 for x in range(10 ** 6))
        s = NonceSearcher(check_interval=100, clock=lambda: next(clock))
        r = s.search(template(), 1, max_seconds=2.0)
        self.assertEqual(r.status, SearchStatus.LIMIT)
        self.assertLess(r.hashes_attempted, 1000)

    def test_interrupt_via_event(self):
        s = NonceSearcher(check_interval=2048)
        threading.Timer(0.2, s.stop).start()
        t0 = time.perf_counter()
        r = s.search(template(), 1)         # would take hours to finish
        self.assertEqual(r.status, SearchStatus.INTERRUPTED)
        self.assertLess(time.perf_counter() - t0, 5)
        self.assertGreater(r.hashes_attempted, 0)
        self.assertEqual(r.next_nonce, r.hashes_attempted)    # resumable, nothing skipped

    def test_graceful_shutdown_on_sigint(self):
        ev = threading.Event()
        s = NonceSearcher(stop_event=ev, check_interval=2048)
        with graceful_shutdown(ev):
            threading.Timer(0.2, lambda: os.kill(os.getpid(), signal.SIGINT)).start()
            r = s.search(template(), 1)
        self.assertEqual(r.status, SearchStatus.INTERRUPTED)
        self.assertIs(signal.getsignal(signal.SIGINT), signal.default_int_handler)  # restored

    def test_progress_callback(self):
        seen = []
        NonceSearcher(check_interval=100).search(template(), 1, 0, 450, progress=lambda h, n: seen.append((h, n)))
        self.assertEqual(seen[-1], (450, 450))
        self.assertEqual([h for h, _ in seen], [100, 200, 300, 400, 450])


class TestExtraNonceVariants(unittest.TestCase):
    def test_varying_header_extends_search_space(self):
        # Each variant stands in for a different coinbase extra nonce / merkle root.
        variants = [(en, template(seed=en)) for en in range(5)]
        # Target = the single best (lowest) hash over all variants x nonces in range,
        # so exactly one (variant, nonce) pair can win and it is known independently.
        best = min(((hash_to_int(BlockHeader.deserialize(h).with_nonce(n).hash()), lbl, n)
                    for lbl, h in variants for n in range(1000)))
        tgt, want_label, want_nonce = best
        r = NonceSearcher().search_variants(variants, tgt, start_nonce=0, end_nonce=1000)
        self.assertTrue(r.found)
        self.assertEqual((r.label, r.nonce), (want_label, want_nonce))
        self.assertEqual(r.hashes_attempted, want_label * 1000 + want_nonce + 1)   # cumulative
        self.assertEqual(r.digest, BlockHeader.deserialize(variants[want_label][1])
                         .with_nonce(want_nonce).hash())

    def test_variants_exhaustion_and_accounting(self):
        s = NonceSearcher()
        small = [(i, template(seed=i)) for i in range(3)]
        r = s.search_variants(small, 1, start_nonce=0, end_nonce=400)
        self.assertEqual((r.status, r.hashes_attempted), (SearchStatus.EXHAUSTED, 1200))
        r = s.search_variants(small, 1, max_hashes=2500, start_nonce=0, end_nonce=1000)
        self.assertEqual((r.status, r.hashes_attempted), (SearchStatus.LIMIT, 2500))
        # An empty variant list searched nothing; it must not claim exhaustion.
        with self.assertRaises(ValueError):
            s.search_variants([], 1)


if __name__ == "__main__":
    unittest.main()
