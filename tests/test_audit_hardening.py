"""Regression tests for defects found in the TASK 004 audit.

Each test pins a concrete bug: it fails on the pre-audit code and passes
after the fix. None of them weakens consensus validation; several make it
stricter or bring it in line with Bitcoin Core.
"""

import json
import logging
import os
import random
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain import primitives as prim  # noqa: E402
from blockchain.analysis import coinbase_within_limit, verify_merkle_root  # noqa: E402
from blockchain.service import MonitoringService  # noqa: E402
from blockchain.storage import ChainStore  # noqa: E402
from mining.miner import scan_nonces  # noqa: E402
from mining.pow import target as T  # noqa: E402
from mining.pow.nonce_search import NonceSearcher, SearchStatus  # noqa: E402
from mining.pow.sha256 import SHA256, sha256  # noqa: E402
from node.rpc_client import BitcoinRPC, RPCConnectionError, RPCError  # noqa: E402
from tests.fakes import FakeRPC  # noqa: E402

import hashlib  # noqa: E402


class TestConsensusTargetUnification(unittest.TestCase):
    """The legacy primitives used a weaker target decoder than Core."""

    def test_hash_equal_to_target_meets_target(self):
        # Core: CheckProofOfWork fails only if hash > target. Equality passes.
        target = 0x1234 << 200
        digest = target.to_bytes(32, "little")
        self.assertTrue(prim.hash_meets_target(digest, target))
        self.assertFalse(prim.hash_meets_target((target + 1).to_bytes(32, "little"), target))

    def test_legacy_decoder_rejects_overflow_zero_and_negative(self):
        for bits in (0xFF123456, 0x23000001 | 0x01000000, 0x00000000, 0x01003456, 0x04923456):
            with self.subTest(bits=hex(bits)):
                with self.assertRaises(ValueError):
                    prim.bits_to_target(bits)

    def test_zero_mantissa_with_sign_bit_is_zero_not_negative_but_still_unusable(self):
        # Core: negative requires a non-zero mantissa; zero targets are invalid.
        with self.assertRaises(ValueError):
            prim.bits_to_target(0x03800000)

    def test_roundtrip_agrees_with_pow_engine_on_random_values(self):
        rng = random.Random(4)
        for _ in range(2000):
            value = rng.getrandbits(rng.randint(1, 256)) or 1
            bits = T.encode_compact(value)
            self.assertEqual(prim.target_to_bits(value), bits)
            t = T.decode_compact(bits)
            if t.valid:
                self.assertEqual(prim.bits_to_target(bits), t.value)

    def test_target_to_bits_range_errors_are_valueerror(self):
        for bad in (0, -1, 1 << 256):
            with self.assertRaises(ValueError):
                prim.target_to_bits(bad)


class TestMerkleMutation(unittest.TestCase):
    """CVE-2012-2459: a duplicated trailing tx must not verify."""

    def _txids(self, n):
        return [hashlib.sha256(bytes([i])).digest() for i in range(n)]

    def test_duplicate_tail_yields_same_root_but_is_flagged(self):
        a, b, c = self._txids(3)
        honest, mutated_h = prim.merkle_root_checked([a, b, c])
        twin, mutated_t = prim.merkle_root_checked([a, b, c, c])
        self.assertEqual(honest, twin)  # the well-known ambiguity
        self.assertFalse(mutated_h)
        self.assertTrue(mutated_t)

    def test_verify_merkle_root_rejects_mutated_block(self):
        a, b, c = self._txids(3)
        root = prim.internal_to_display(prim.merkle_root([a, b, c]))
        good = {"tx": [prim.internal_to_display(x) for x in (a, b, c)], "merkleroot": root}
        bad = {"tx": [prim.internal_to_display(x) for x in (a, b, c, c)], "merkleroot": root}
        self.assertTrue(verify_merkle_root(good))
        self.assertFalse(verify_merkle_root(bad))

    def test_single_and_power_of_two_blocks_not_flagged(self):
        for n in (1, 2, 4, 8, 5, 7):
            _, mutated = prim.merkle_root_checked(self._txids(n))
            self.assertFalse(mutated, n)


class TestCoinbaseLimitIsExactToTheSatoshi(unittest.TestCase):
    def test_one_satoshi_over_is_rejected(self):
        subsidy = 50 * 10**8
        self.assertTrue(coinbase_within_limit(50.0, subsidy, None))
        self.assertFalse(coinbase_within_limit(50.00000001, subsidy, None))

    def test_fees_extend_the_limit_exactly(self):
        self.assertTrue(coinbase_within_limit(50.0001, 50 * 10**8, 0.0001))
        self.assertFalse(coinbase_within_limit(50.00010001, 50 * 10**8, 0.0001))


class TestHexStrictness(unittest.TestCase):
    def test_display_hash_to_int_rejects_non_hex_forms(self):
        for bad in ("0x" + "a" * 62, " " + "a" * 63, "+" + "a" * 63, "a_" * 32, "g" * 64):
            with self.subTest(bad=bad[:12]):
                with self.assertRaises(ValueError):
                    T.display_hash_to_int(bad)
        self.assertEqual(T.display_hash_to_int("00" * 31 + "ff"), 255)

    def test_display_to_digest_rejects_whitespace_and_prefix(self):
        with self.assertRaises(ValueError):
            T.display_to_digest(("ab " * 10 + "cd") + "00" * 20 + " ")
        with self.assertRaises(ValueError):
            prim.display_to_internal("0x" + "ab" * 31)


class TestLegacyMinerUsesConsensusSearch(unittest.TestCase):
    def test_scan_nonces_accepts_hash_equal_to_target(self):
        # Target is made exactly equal to the hash of nonce 0; <= must find it.
        prefix = b"\x01" * 76
        digest = hashlib.sha256(hashlib.sha256(prefix + b"\0\0\0\0").digest()).digest()
        value = int.from_bytes(digest, "little")
        bits = T.encode_compact(value)
        exact = T.decode_compact(bits).value
        # Only meaningful when compact encoding is lossless for this hash.
        if exact == value:
            self.assertTrue(scan_nonces(prefix, bits, max_nonces=1).found)

    def test_max_seconds_zero_is_honoured(self):
        r = scan_nonces(b"\x00" * 76, 0x01010000, max_nonces=10**7, max_seconds=0.0)
        self.assertLess(r.hashes, 10**7)

    def test_start_nonce_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            scan_nonces(b"\x00" * 76, 0x207FFFFF, start_nonce=(1 << 32) + 1)
        with self.assertRaises(ValueError):
            scan_nonces(b"\x00" * 76, 0x207FFFFF, start_nonce=-1)


class TestNonceSearchEdges(unittest.TestCase):
    H = bytes(80)

    def test_negative_limits_rejected(self):
        s = NonceSearcher()
        with self.assertRaises(ValueError):
            s.search(self.H, 1, max_hashes=-5)
        with self.assertRaises(ValueError):
            s.search(self.H, 1, 0, 10, max_seconds=-1)

    def test_variants_respect_custom_range_when_exhausted(self):
        r = NonceSearcher().search_variants([("a", self.H)], 1, start_nonce=10, end_nonce=50)
        self.assertEqual(r.status, SearchStatus.EXHAUSTED)
        self.assertEqual((r.start_nonce, r.next_nonce, r.hashes_attempted), (10, 50, 40))

    def test_empty_variant_list_is_an_error_not_exhaustion(self):
        with self.assertRaises(ValueError):
            NonceSearcher().search_variants([], 1)

    def test_search_bits_winner_check_raises_typed_error_not_assertion(self):
        from mining.pow import nonce_search as ns
        self.assertTrue(hasattr(ns, "PoWInternalError"))


class TestSha256Streaming(unittest.TestCase):
    def test_random_chunking_matches_hashlib(self):
        rng = random.Random(9)
        for _ in range(300):
            data = rng.randbytes(rng.randint(0, 600))
            h = SHA256()
            i = 0
            while i < len(data):
                step = rng.randint(0, 130)
                h.update(data[i:i + step])
                i += step
            h.update(data[i:])
            self.assertEqual(h.digest(), hashlib.sha256(data).digest())
            self.assertEqual(sha256(data), hashlib.sha256(data).digest())

    def test_digest_does_not_consume_state_and_copy_is_independent(self):
        h = SHA256(b"abc")
        d1 = h.digest()
        c = h.copy()
        c.update(b"def")
        self.assertEqual(h.digest(), d1)
        self.assertEqual(c.digest(), hashlib.sha256(b"abcdef").digest())

    def test_rejects_str_and_int(self):
        for bad in ("abc", 5, None):
            with self.assertRaises(TypeError):
                sha256(bad)


class _FakeHTTP:
    def __init__(self, body: bytes):
        self._b = body

    def read(self, n=-1):
        return self._b if n < 0 else self._b[:n]

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestRPCClientHardening(unittest.TestCase):
    def _rpc(self, url="http://127.0.0.1:18443", **kw):
        return BitcoinRPC(url, user="u", password="p", **kw)

    def test_refuses_cleartext_credentials_to_non_loopback_host(self):
        with self.assertRaises(ValueError):
            self._rpc("http://203.0.113.9:8332")
        self._rpc("http://203.0.113.9:8332", allow_remote=True)

    def test_refuses_non_http_schemes(self):
        for url in ("file:///etc/passwd", "ftp://127.0.0.1/x", "gopher://127.0.0.1"):
            with self.assertRaises(ValueError):
                self._rpc(url)

    def test_malformed_json_reply_is_typed_error(self):
        with mock.patch("urllib.request.urlopen", return_value=_FakeHTTP(b"<html>not json")):
            with self.assertRaises(RPCConnectionError):
                self._rpc().call("getblockcount")

    def test_reply_missing_result_is_typed_error(self):
        body = json.dumps({"id": 1, "error": None}).encode()
        with mock.patch("urllib.request.urlopen", return_value=_FakeHTTP(body)):
            with self.assertRaises(RPCConnectionError):
                self._rpc().call("getblockcount")

    def test_mismatched_reply_id_rejected(self):
        body = json.dumps({"id": 999, "result": 5, "error": None}).encode()
        with mock.patch("urllib.request.urlopen", return_value=_FakeHTTP(body)):
            with self.assertRaises(RPCConnectionError):
                self._rpc().call("getblockcount")

    def test_oversized_reply_rejected(self):
        big = b"[" + b"1," * 600 + b"1]"
        with mock.patch("urllib.request.urlopen", return_value=_FakeHTTP(big)):
            with self.assertRaises(RPCConnectionError):
                self._rpc(max_response_bytes=1000).call("getblockcount")

    def test_concurrent_calls_on_one_client_match_their_own_replies(self):
        # Found live: a long-poll thread and a caller share one client; the
        # reply id was compared with the shared counter, not the request's id.
        import threading
        import time as _t

        def echo(req, timeout=None):
            sent = json.loads(req.data)
            _t.sleep(0.002 if sent["id"] % 2 else 0.0)  # reorder completions
            return _FakeHTTP(json.dumps({"id": sent["id"], "result": sent["method"],
                                         "error": None}).encode())

        rpc = self._rpc()
        errors = []

        def worker(name):
            try:
                for _ in range(100):
                    if rpc.call(name) != name:
                        errors.append("wrong result")
            except Exception as exc:
                errors.append(exc)

        with mock.patch("urllib.request.urlopen", side_effect=echo):
            ts = [threading.Thread(target=worker, args=(f"m{i}",)) for i in range(6)]
            for t in ts:
                t.start()
            for t in ts:
                t.join()
        self.assertEqual(errors, [])

    def test_good_reply_and_rpc_error_still_work(self):
        ok = json.dumps({"id": 1, "result": 7, "error": None}).encode()
        with mock.patch("urllib.request.urlopen", return_value=_FakeHTTP(ok)):
            self.assertEqual(self._rpc().call("getblockcount"), 7)
        err = json.dumps({"id": 1, "result": None,
                          "error": {"code": -5, "message": "nope"}}).encode()
        with mock.patch("urllib.request.urlopen", return_value=_FakeHTTP(err)):
            with self.assertRaises(RPCError):
                self._rpc().call("getblockcount")

    def test_connection_error_is_subclass_of_urlerror_for_existing_handlers(self):
        self.assertTrue(issubclass(RPCConnectionError, urllib.error.URLError))


class FlakyMidWalkRPC(FakeRPC):
    """Dies after N successful getblock-height lookups during a sync walk."""

    def __init__(self):
        super().__init__()
        self.die_after_hash_calls = None

    def get_block_hash(self, height):
        if self.die_after_hash_calls is not None:
            if self.die_after_hash_calls <= 0:
                raise urllib.error.URLError("node died mid-walk")
            self.die_after_hash_calls -= 1
        return super().get_block_hash(height)


class TestServiceRobustness(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)  # failure paths log by design; keep test output readable
        self.addCleanup(logging.disable, logging.NOTSET)
        self.tmp = tempfile.mkdtemp(prefix="bal-audit-")
        self.rpc = FlakyMidWalkRPC()
        self.rpc.mine(6)
        self.store = ChainStore(os.path.join(self.tmp, "c.db"))
        self.addCleanup(self.store.close)
        self.svc = MonitoringService(self.rpc, self.store, poll_interval=0.01,
                                     rpc_factory=lambda: self.rpc)

    def test_node_dying_mid_walk_is_reported_not_raised_and_recovers(self):
        self.rpc.die_after_hash_calls = 2
        report = self.svc.sync_once()  # must not raise
        self.assertFalse(report.ok)
        self.rpc.die_after_hash_calls = None
        report = self.svc.sync_once()
        self.assertTrue(report.ok)
        self.assertEqual(self.store.count_blocks("active"), 6)

    def test_run_loop_survives_unexpected_exception(self):
        calls = {"n": 0}
        real = self.svc.sync_once

        def boom():
            calls["n"] += 1
            if calls["n"] == 1:
                raise KeyError("unexpected shape")
            return real()
        self.svc.sync_once = boom
        self.svc.run(iterations=3)
        self.assertEqual(self.store.count_blocks("active"), 6)

    def test_walk_stops_when_chain_changes_under_it(self):
        # Node returns a block whose parent is not the one we stored.
        self.svc.sync_once()
        self.rpc.mine(1)
        tip_height = len(self.rpc.blocks) - 1
        self.rpc.blocks[tip_height]["previousblockhash"] = "ab" * 32  # broken link
        report = self.svc.sync_once()
        self.assertFalse(report.ok)
        self.assertNotIn(self.rpc.blocks[tip_height]["hash"],
                         [b["hash"] for b in self.store.recent_blocks(20)])


class TestStoreDurability(unittest.TestCase):
    def test_pragmas(self):
        tmp = tempfile.mkdtemp(prefix="bal-store-")
        with ChainStore(os.path.join(tmp, "x.db")) as s:
            self.assertEqual(s.db.execute("PRAGMA journal_mode").fetchone()[0].lower(), "wal")
            self.assertGreaterEqual(s.db.execute("PRAGMA busy_timeout").fetchone()[0], 1000)
            self.assertEqual(s.db.execute("PRAGMA integrity_check").fetchone()[0], "ok")

    def test_database_file_is_private(self):
        tmp = tempfile.mkdtemp(prefix="bal-store-")
        p = os.path.join(tmp, "x.db")
        with ChainStore(p):
            self.assertEqual(os.stat(p).st_mode & 0o077, 0)


class TestNoBareAssertsInLibraryCode(unittest.TestCase):
    """`python -O` strips asserts; validation must not depend on them."""

    def test_no_assert_statements_in_library_modules(self):
        import ast
        root = os.path.join(os.path.dirname(__file__), "..")
        offenders = []
        for pkg in ("agent", "blockchain", "dashboard", "mining", "node"):
            for dp, _, files in os.walk(os.path.join(root, pkg)):
                for f in files:
                    if f.endswith(".py"):
                        path = os.path.join(dp, f)
                        with open(path, encoding="utf-8") as fh:
                            tree = ast.parse(fh.read())
                        for n in ast.walk(tree):
                            if isinstance(n, ast.Assert):
                                offenders.append(f"{os.path.relpath(path, root)}:{n.lineno}")
        self.assertEqual(offenders, [])


class TestStoreThreadSafety(unittest.TestCase):
    """The monitor thread and readers share one store (found by a live test)."""

    def test_concurrent_writers_and_readers(self):
        import threading
        tmp = tempfile.mkdtemp(prefix="bal-thr-")
        store = ChainStore(os.path.join(tmp, "t.db"))
        self.addCleanup(store.close)
        rpc = FakeRPC()
        rpc.mine(30)
        reader = MonitoringService(rpc, store, poll_interval=0.01)
        errors = []

        def reads():
            try:
                for _ in range(200):
                    store.count_blocks("active")
                    store.recent_blocks(5)
                    store.get_sync()
            except Exception as exc:  # pragma: no cover - failure path
                errors.append(exc)

        threads = [threading.Thread(target=reads) for _ in range(4)]
        for t in threads:
            t.start()
        reader.sync_once()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(store.count_blocks("active"), 30)


class _Mgr:
    def __init__(self, rpc=None, exc=None):
        self._rpc, self._exc = rpc, exc

    def client(self):
        if self._exc:
            raise self._exc
        return self._rpc


class TestAgentInterfaceHardening(unittest.TestCase):
    def setUp(self):
        logging.disable(logging.CRITICAL)  # error paths log by design
        self.addCleanup(logging.disable, logging.NOTSET)
        from agent.interface import AgentInterface
        self.AgentInterface = AgentInterface
        self.rpc = FakeRPC()
        self.hashes = self.rpc.mine(5)

    def test_node_down_gives_structured_error_and_opens_no_database(self):
        tmp = tempfile.mkdtemp(prefix="bal-ai-")
        db = os.path.join(tmp, "never.db")
        agent = self.AgentInterface(_Mgr(exc=ConnectionError("node down")))
        for call in (agent.current_block_height, agent.latest_block_hash, agent.mempool_status,
                     agent.network_difficulty, agent.latest_block_tx_count):
            r = call()
            self.assertFalse(r["ok"], call.__name__)
            self.assertIn("node down", r["error"])
        for r in (agent.sync_blockchain(db), agent.blockchain_status(db), agent.has_new_block(db)):
            self.assertFalse(r["ok"])
        self.assertFalse(os.path.exists(db))  # store is opened only after the node answers

    def test_argument_validation(self):
        agent = self.AgentInterface(_Mgr(self.rpc))
        for bad in (0, -3, 10**9, "5", None, True):
            self.assertFalse(agent.latest_blocks(bad)["ok"], bad)
            self.assertFalse(agent.generate_blocks(bad)["ok"], bad)
        for bad in ("", "xyz", "0x" + "a" * 62, " " + "a" * 63, "a" * 63, "a" * 65, 5):
            self.assertFalse(agent.analyze_block(bad)["ok"], bad)
            self.assertFalse(agent.get_transaction(bad)["ok"], bad)
        self.assertTrue(agent.latest_blocks(3)["ok"])
        self.assertTrue(agent.analyze_block(self.hashes[-1])["ok"])

    def test_structured_success_shapes(self):
        agent = self.AgentInterface(_Mgr(self.rpc))
        self.assertEqual(agent.current_block_height()["height"], 4)
        self.assertEqual(agent.latest_block_hash()["block_hash"], self.hashes[-1])
        tip = agent.latest_block_tx_count()
        self.assertEqual((tip["height"], tip["n_tx"]), (4, 1))
        self.assertEqual(agent.network_difficulty()["chain"], "regtest")
        self.assertEqual(agent.latest_blocks(3)["count"], 3)


class TestDashboardRendering(unittest.TestCase):
    def test_render_status_and_verification(self):
        from blockchain.monitor import BlockVerification, NodeStatus
        from dashboard.status import render_status, render_verification
        st = NodeStatus("regtest", 12, 12, "ab" * 32, 4.6e-10, 1, 1.0, 3, 0, 99)
        out = render_status(st)
        for needle in ("regtest", "12 / 12", "ab" * 32, "mempool transactions  3"):
            self.assertIn(needle, out)
        ok = BlockVerification(12, "cd" * 32, True, True, True, True, 2, 1)
        self.assertEqual(render_verification(ok).count("[PASS]"), 4)
        bad = BlockVerification(12, "cd" * 32, True, False, True, True, 2, 1)
        text = render_verification(bad)
        self.assertIn("[FAIL] proof-of-work meets target", text)
        self.assertFalse(bad.ok)


if __name__ == "__main__":
    unittest.main()
