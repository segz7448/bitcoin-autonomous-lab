"""Adversarial tests: boundary values, malformed inputs, failure paths.

These probe the places miners actually break: compact target edge cases,
nonce range limits, BIP34 script encoding boundaries, oversized/undersized
fields, RPC failures, template anomalies, and the regtest-only guard.
"""

import json
import os
import sys
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain.primitives import (  # noqa: E402
    BlockHeader, bits_to_target, display_to_internal,
    encode_varint, internal_to_display, merkle_root, push_data, script_num_push,
    sha256d_fast, target_to_bits,
)
from mining.block import build_coinbase_tx  # noqa: E402
from mining.miner import scan_nonces  # noqa: E402
from mining.template_miner import (  # noqa: E402
    build_block_from_template, mine_one_block, require_regtest,
)
from node.rpc_client import BitcoinRPC, RPCError  # noqa: E402


class TestTargetEncodings(unittest.TestCase):
    def test_pow_limit_exact(self):
        self.assertEqual(bits_to_target(0x1D00FFFF), 0xFFFF << 208)

    def test_small_exponent_shifts_right(self):
        self.assertEqual(bits_to_target(0x03123456), 0x123456)
        self.assertEqual(bits_to_target(0x01010000), 1)  # target of 1

    def test_negative_mantissa_rejected(self):
        with self.assertRaises(ValueError):
            bits_to_target(0x1D800001)  # sign bit set

    def test_roundtrip_valid_range(self):
        # Compact encoding round-trips for full 3-byte mantissas; smaller
        # targets have non-unique encodings by design.
        for exponent in range(3, 33):
            for mantissa in (0x010000, 0x123456, 0x7FFFFF):
                bits = (exponent << 24) | mantissa
                with self.subTest(bits=hex(bits)):
                    self.assertEqual(target_to_bits(bits_to_target(bits)), bits)

    def test_target_out_of_range_rejected(self):
        with self.assertRaises(ValueError):
            target_to_bits(0)
        with self.assertRaises((ValueError, OverflowError)):
            target_to_bits(1 << 256)


class TestNonceBounds(unittest.TestCase):
    def test_prefix_length_enforced(self):
        with self.assertRaises(ValueError):
            scan_nonces(b"\x00" * 75, 0x207FFFFF)
        with self.assertRaises(ValueError):
            scan_nonces(b"\x00" * 77, 0x207FFFFF)

    def test_scan_clamps_at_uint32_boundary(self):
        # Impossible target (1): the scan must stop at 2^32, not overflow.
        result = scan_nonces(b"\x00" * 76, 0x01010000,
                             start_nonce=0xFFFFFFFE, max_nonces=100)
        self.assertFalse(result.found)
        self.assertEqual(result.hashes, 2)

    def test_zero_length_scan(self):
        result = scan_nonces(b"\x00" * 76, 0x207FFFFF, max_nonces=0)
        self.assertFalse(result.found)
        self.assertEqual(result.hashes, 0)


class TestBIP34Boundaries(unittest.TestCase):
    # Expected encodings mirror CScript::operator<<(int64_t).
    CASES = {
        0: b"\x00",                 # OP_0
        1: b"\x51",                 # OP_1
        16: b"\x60",                # OP_16
        17: b"\x01\x11",            # smallest data push
        127: b"\x01\x7f",
        128: b"\x02\x80\x00",       # sign byte needed
        255: b"\x02\xff\x00",
        256: b"\x02\x00\x01",
        32767: b"\x02\xff\x7f",
        32768: b"\x03\x00\x80\x00",  # sign byte needed
        -1: b"\x01\x81",            # CScriptNum negative one
    }

    def test_height_encodings(self):
        for height, expected in self.CASES.items():
            with self.subTest(height=height):
                self.assertEqual(script_num_push(height), expected)


class TestMalformedInputs(unittest.TestCase):
    def test_display_hash_wrong_length(self):
        with self.assertRaises(ValueError):
            display_to_internal("abcd")
        with self.assertRaises(ValueError):
            internal_to_display(b"\x00" * 31)

    def test_display_hash_bad_hex(self):
        with self.assertRaises(ValueError):
            display_to_internal("zz" * 32)

    def test_empty_merkle_rejected(self):
        with self.assertRaises(ValueError):
            merkle_root([])

    def test_oversized_push_rejected(self):
        with self.assertRaises(ValueError):
            push_data(b"x" * 76)

    def test_coinbase_scriptsig_consensus_limits(self):
        # 2-100 bytes (CheckTransaction). Height 1 + empty extranonce = 1 byte.
        with self.assertRaises(ValueError):
            build_coinbase_tx(1, 50, bytes.fromhex("51"), extranonce=b"")
        # Extranonce pushing past 100 bytes.
        with self.assertRaises(ValueError):
            build_coinbase_tx(1, 50, bytes.fromhex("51"), extranonce=b"x" * 200)

    def test_bad_header_hex_rejected(self):
        header = BlockHeader(1, "gg" * 32, "00" * 32, 0, 0x207FFFFF, 0)
        with self.assertRaises(ValueError):
            header.serialize()

    def test_witness_commitment_length_enforced(self):
        with self.assertRaises(ValueError):
            build_coinbase_tx(1, 50, bytes.fromhex("51"),
                              witness_commitment=b"\x00" * 31)


class TestVarintBoundaries(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(encode_varint(0xFC), bytes([0xFC]))
        self.assertEqual(encode_varint(0xFD), b"\xfd\xfd\x00")
        self.assertEqual(encode_varint(0xFFFF), b"\xfd\xff\xff")
        self.assertEqual(encode_varint(0x10000), b"\xfe\x00\x00\x01\x00")


class TestWitnessCommitmentConstruction(unittest.TestCase):
    def test_commitment_layout(self):
        commitment = b"\x11" * 32
        cb = build_coinbase_tx(100, 50, bytes.fromhex("51"),
                               witness_commitment=commitment)
        self.assertNotEqual(cb.stripped, cb.full)
        # txid commits to the stripped serialization only.
        self.assertEqual(cb.txid_internal, sha256d_fast(cb.stripped))
        # Witness marker/flag follow the version in the full serialization.
        self.assertEqual(cb.full[4:6], b"\x00\x01")
        # Commitment sits in an OP_RETURN output in both serializations
        # (outputs are part of the stripped form).
        self.assertIn(b"\xaa\x21\xa9\xed" + commitment, cb.stripped)
        self.assertIn(b"\xaa\x21\xa9\xed" + commitment, cb.full)

    def test_template_with_witness_tx_gets_commitment(self):
        template = {
            "height": 5, "coinbasevalue": 5_000_000_000,
            "version": 0x20000000, "previousblockhash": "00" * 32,
            "curtime": 1296688602, "mintime": 1296688602, "bits": "207fffff",
            "transactions": [
                {"txid": "11" * 32, "hash": "22" * 32, "data": "0a0b0c"},
            ],
        }
        header, txs, witness_count = build_block_from_template(
            template, bytes.fromhex("51"))
        self.assertEqual(witness_count, 1)
        self.assertEqual(len(txs), 2)
        self.assertEqual(txs[0][4:6], b"\x00\x01")  # coinbase has witness
        self.assertEqual(txs[1], bytes.fromhex("0a0b0c"))

    def test_template_without_witness_tx_has_no_commitment(self):
        template = {
            "height": 5, "coinbasevalue": 5_000_000_000,
            "version": 0x20000000, "previousblockhash": "00" * 32,
            "curtime": 1296688602, "mintime": 1296688602, "bits": "207fffff",
            "transactions": [
                {"txid": "11" * 32, "hash": "11" * 32, "data": "0a0b0c"},
            ],
        }
        header, txs, witness_count = build_block_from_template(
            template, bytes.fromhex("51"))
        self.assertEqual(witness_count, 0)
        self.assertNotEqual(txs[0][4:6], b"\x00\x01")

    def test_commitment_mismatch_fails_closed(self):
        template = {
            "height": 5, "coinbasevalue": 5_000_000_000,
            "version": 0x20000000, "previousblockhash": "00" * 32,
            "curtime": 1296688602, "mintime": 1296688602, "bits": "207fffff",
            "transactions": [
                {"txid": "11" * 32, "hash": "22" * 32, "data": "0a0b0c"},
            ],
            # A default_witness_commitment that disagrees with our computed
            # commitment must abort, not submit.
            "default_witness_commitment": "6a24aa21a9ed" + "ff" * 32,
        }
        with self.assertRaises(RuntimeError):
            build_block_from_template(template, bytes.fromhex("51"))

    def test_template_tx_missing_fields_fails_closed(self):
        template = {
            "height": 5, "coinbasevalue": 5_000_000_000,
            "version": 0x20000000, "previousblockhash": "00" * 32,
            "curtime": 1296688602, "mintime": 1296688602, "bits": "207fffff",
            "transactions": [{"txid": "11" * 32}],  # no "data"
        }
        with self.assertRaises(RuntimeError):
            build_block_from_template(template, bytes.fromhex("51"))


class _StubRPC:
    """Canned node: one empty template; submitblock scripted to accept/reject."""

    def __init__(self, reject=None):
        self.reject = reject
        self.submitted = None

    def get_block_template(self, rules=None):
        return {
            "height": 1, "coinbasevalue": 5_000_000_000,
            "version": 0x20000000, "previousblockhash": "00" * 32,
            "curtime": 1296688602, "mintime": 1296688602, "bits": "207fffff",
            "transactions": [],
        }

    def submit_block(self, block_hex):
        self.submitted = block_hex
        return self.reject

    def get_block(self, block_hash, verbosity=1):
        return {"confirmations": 1}


class TestSubmissionPaths(unittest.TestCase):
    def test_rejected_block_raises(self):
        with self.assertRaises(RuntimeError):
            mine_one_block(_StubRPC(reject="bad-test"), bytes.fromhex("51"),
                           verbose=False)

    def test_accepted_block_returns_evidence(self):
        rpc = _StubRPC()
        evidence = mine_one_block(rpc, bytes.fromhex("51"), verbose=False)
        self.assertTrue(evidence["accepted"])
        self.assertIsNotNone(rpc.submitted)
        self.assertEqual(evidence["confirmations"], 1)


class TestRegtestGuard(unittest.TestCase):
    def test_only_regtest_allowed(self):
        require_regtest("regtest")
        for chain in ("main", "test", "testnet3", "testnet4", "signet", ""):
            with self.subTest(chain=chain):
                with self.assertRaises(RuntimeError):
                    require_regtest(chain)


class _ErrorHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        body = json.dumps({
            "jsonrpc": "1.0", "id": 1, "result": None,
            "error": {"code": -8, "message": "simulated node error"},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class TestRPCFailures(unittest.TestCase):
    def test_auth_required(self):
        with self.assertRaises(ValueError):
            BitcoinRPC("http://127.0.0.1:1")

    def test_connection_refused(self):
        rpc = BitcoinRPC("http://127.0.0.1:9", user="u", password="p")
        with self.assertRaises(urllib.error.URLError):
            rpc.call("getblockchaininfo")

    def test_rpc_error_payload_raises(self):
        server = HTTPServer(("127.0.0.1", 0), _ErrorHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            port = server.server_address[1]
            rpc = BitcoinRPC(f"http://127.0.0.1:{port}", user="u", password="p")
            with self.assertRaises(RPCError) as ctx:
                rpc.call("getblocktemplate")
            self.assertEqual(ctx.exception.code, -8)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
