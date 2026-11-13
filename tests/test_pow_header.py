"""Block header serialization/deserialization/hashing vs real mainnet headers."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import struct

from mining.pow.block_header import BlockHeader, hash_header_bytes
from mining.pow.validator import validate_header
from tests.pow_fixtures import GENESIS, MAINNET


class TestHeader(unittest.TestCase):
    def test_real_mainnet_headers_hash_to_known_block_hashes(self):
        for f in MAINNET:
            with self.subTest(height=f["height"]):
                raw = bytes.fromhex(f["header"])
                self.assertEqual(len(raw), 80)
                h = BlockHeader.deserialize(raw)
                self.assertEqual(h.serialize(), raw)               # byte-exact round trip
                self.assertEqual(h.hash_display(), f["hash"])      # own SHA-256
                self.assertEqual(h.hash_fast(), h.hash())          # OpenSSL agrees
                self.assertEqual(hash_header_bytes(raw)[::-1].hex(), f["hash"])
                self.assertTrue(validate_header(h).valid)

    def test_field_layout_genesis(self):
        h = BlockHeader.from_hex(GENESIS["header"])
        self.assertEqual(h.version, 1)
        self.assertEqual(h.prev_hash, bytes(32))
        self.assertEqual(h.merkle_root_display,
                         "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b")
        self.assertEqual((h.time, h.bits, h.nonce), (1231006505, 0x1D00FFFF, 2083236893))

    def test_little_endian_and_hash_byte_order(self):
        h = BlockHeader.from_display(2, "11" * 31 + "22", "33" * 31 + "44", 1, 2, 3)
        raw = h.serialize()
        self.assertEqual(raw[0:4], b"\x02\x00\x00\x00")
        self.assertEqual(raw[4:36], bytes.fromhex("22" + "11" * 31))   # reversed
        self.assertEqual(raw[36:68], bytes.fromhex("44" + "33" * 31))
        self.assertEqual(raw[68:72], b"\x01\x00\x00\x00")
        self.assertEqual(raw[72:76], b"\x02\x00\x00\x00")
        self.assertEqual(raw[76:80], b"\x03\x00\x00\x00")
        self.assertEqual(h.prev_hash_display, "11" * 31 + "22")

    def test_negative_version_signed(self):
        h = BlockHeader(-1, bytes(32), bytes(32), 0, 0, 0)
        self.assertEqual(h.serialize()[:4], b"\xff\xff\xff\xff")
        self.assertEqual(BlockHeader.deserialize(h.serialize()).version, -1)

    def test_strict_size_validation(self):
        good = bytes.fromhex(GENESIS["header"])
        for bad in (b"", good[:79], good + b"\x00", good[:-1] + b"\x00\x00", bytes(81), bytes(160)):
            with self.subTest(len=len(bad)):
                with self.assertRaises(ValueError):
                    BlockHeader.deserialize(bad)
                with self.assertRaises(ValueError):
                    hash_header_bytes(bad)
        with self.assertRaises(ValueError):
            BlockHeader.from_hex(GENESIS["header"][:-2])

    def test_field_range_validation(self):
        z = bytes(32)
        for args in ((2 ** 31, z, z, 0, 0, 0), (-2 ** 31 - 1, z, z, 0, 0, 0),
                     (1, bytes(31), z, 0, 0, 0), (1, z, bytes(33), 0, 0, 0),
                     (1, z, z, -1, 0, 0), (1, z, z, 2 ** 32, 0, 0),
                     (1, z, z, 0, 2 ** 32, 0), (1, z, z, 0, 0, 2 ** 32), (1, z, z, 0, 0, -1),
                     (True, z, z, 0, 0, 0)):
            with self.subTest(args=args[:1] + args[3:]):
                with self.assertRaises(ValueError):
                    BlockHeader(*args)
        with self.assertRaises(ValueError):
            BlockHeader.from_display(1, "00" * 31, "00" * 32, 0, 0, 0)

    def test_nonce_boundaries(self):
        for n in (0, 1, 0x7FFFFFFF, 0x80000000, 0xFFFFFFFF):
            h = BlockHeader.from_hex(GENESIS["header"]).with_nonce(n)
            self.assertEqual(struct.unpack("<I", h.serialize()[76:])[0], n)
            self.assertEqual(BlockHeader.deserialize(h.serialize()).nonce, n)

    def test_single_bit_flip_changes_hash(self):
        raw = bytearray.fromhex(GENESIS["header"])
        base = hash_header_bytes(bytes(raw))
        for i in (0, 4, 36, 68, 72, 76, 79):
            r = bytearray(raw)
            r[i] ^= 1
            self.assertNotEqual(hash_header_bytes(bytes(r)), base)

    def test_tampered_real_header_fails_pow(self):
        raw = bytearray.fromhex(MAINNET[3]["header"])      # block 125552
        raw[76] ^= 0xFF                                      # break the nonce
        v = validate_header(bytes(raw))
        self.assertFalse(v.valid)
        self.assertEqual(v.reason, "high-hash")


if __name__ == "__main__":
    unittest.main()
