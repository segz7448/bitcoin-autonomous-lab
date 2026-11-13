"""Proof-of-Work validation: valid, invalid, and consensus-edge rejections."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mining.pow.block_header import BlockHeader
from mining.pow.nonce_search import NonceSearcher
from mining.pow.target import POW_LIMIT_REGTEST
from mining.pow.validator import validate_header
from tests.pow_fixtures import MAINNET


def hdr(bits, nonce=0):
    return BlockHeader(1, bytes(32), bytes(range(32)), 1_600_000_000, bits, nonce)


class TestValidator(unittest.TestCase):
    def test_all_real_blocks_valid(self):
        for f in MAINNET:
            v = validate_header(bytes.fromhex(f["header"]))
            self.assertTrue(v.valid, f["height"])
            self.assertEqual((v.reason, v.hash_display), ("ok", f["hash"]))
            self.assertLessEqual(v.hash_int, v.target)

    def test_real_block_with_changed_fields_rejected(self):
        for f in MAINNET:
            raw = bytes.fromhex(f["header"])
            for off in (4, 36, 68, 76):        # prev, merkle, time, nonce
                bad = bytearray(raw)
                bad[off] ^= 0x01
                v = validate_header(bytes(bad))
                self.assertEqual((v.valid, v.reason), (False, "high-hash"), (f["height"], off))

    def test_harder_bits_on_real_block_rejected(self):
        raw = bytearray.fromhex(MAINNET[4]["header"])      # block 300000
        raw[72:76] = (0x1700FFFF).to_bytes(4, "little")      # much lower target
        self.assertEqual(validate_header(bytes(raw)).reason, "high-hash")

    def test_invalid_bits_reasons(self):
        self.assertEqual(validate_header(hdr(0)).reason, "zero-target")
        self.assertEqual(validate_header(hdr(0x04923456)).reason, "negative-target")
        self.assertEqual(validate_header(hdr(0xFF123456)).reason, "overflow-target")
        self.assertEqual(validate_header(hdr(0x1E00FFFF)).reason, "target-above-limit")
        self.assertTrue(validate_header(hdr(0x1E00FFFF), POW_LIMIT_REGTEST).reason != "target-above-limit")

    def test_engine_solutions_validate_and_neighbours_are_independent(self):
        h = hdr(0x1F00FFFF)   # ~2^16 expected hashes: quick but non-trivial
        r = NonceSearcher().search_bits(h.serialize(), POW_LIMIT_REGTEST)
        self.assertTrue(r.found)
        self.assertTrue(validate_header(h.with_nonce(r.nonce), POW_LIMIT_REGTEST).valid)
        self.assertGreater(r.nonce, 0)
        self.assertFalse(validate_header(h.with_nonce(r.nonce - 1), POW_LIMIT_REGTEST).valid)

    def test_rejects_wrong_length_input(self):
        for bad in (bytes(79), bytes(81)):
            with self.assertRaises(ValueError):
                validate_header(bad)


if __name__ == "__main__":
    unittest.main()
