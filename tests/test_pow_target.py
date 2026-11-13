"""nBits decoding, consensus target constraints, difficulty arithmetic."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mining.pow.target import (
    BITS_MAINNET_LIMIT, BITS_REGTEST_LIMIT, MAX_UINT256, POW_LIMIT_MAINNET, POW_LIMIT_REGTEST,
    bits_to_target, check_proof_of_work, decode_compact, display_hash_to_int,
    display_to_digest, digest_to_display, encode_compact, hash_to_int,
)
from mining.pow.difficulty import block_work, difficulty_from_bits, difficulty_from_target, expected_hashes


class TestCompact(unittest.TestCase):
    def test_core_arith_uint256_vectors(self):
        # (nBits, value, negative, overflow) from Bitcoin Core's arith_uint256_tests.
        cases = [
            (0x00000000, 0, False, False), (0x00123456, 0, False, False),
            (0x01003456, 0, False, False), (0x02000056, 0, False, False),
            (0x03000000, 0, False, False), (0x04000000, 0, False, False),
            (0x00923456, 0, False, False), (0x01803456, 0, False, False),
            (0x02800056, 0, False, False), (0x03800000, 0, False, False),
            (0x04800000, 0, False, False),
            (0x01123456, 0x12, False, False), (0x01FEDCBA, 0x7E, True, False),
            (0x02123456, 0x1234, False, False), (0x03123456, 0x123456, False, False),
            (0x04123456, 0x12345600, False, False), (0x04923456, 0x12345600, True, False),
            (0x05009234, 0x92340000, False, False),
            (0x20123456, 0x123456 << (8 * 29), False, False),
        ]
        for bits, value, neg, ovf in cases:
            with self.subTest(bits=hex(bits)):
                t = decode_compact(bits)
                self.assertEqual((t.value, t.negative, t.overflow), (value, neg, ovf))

    def test_overflow(self):
        # Core rule: word != 0 and (size > 34 or (word > 0xff and size > 33)
        #                          or (word > 0xffff and size > 32))
        for bits, want in [(0xFF123456, True), (0x23000100, True), (0x22000100, True),
                           (0x22000001, False), (0x21010000, True), (0x21000100, False),
                           (0x20007FFF, False), (0x23000000, False)]:
            with self.subTest(bits=hex(bits)):
                self.assertEqual(decode_compact(bits).overflow, want)
                self.assertEqual(decode_compact(bits).valid and True, not want and decode_compact(bits).value > 0)

    def test_known_targets(self):
        self.assertEqual(bits_to_target(BITS_MAINNET_LIMIT), POW_LIMIT_MAINNET)
        self.assertEqual(bits_to_target(BITS_REGTEST_LIMIT), POW_LIMIT_REGTEST)
        self.assertEqual(bits_to_target(0x1B0404CB), 0x0404CB * 2 ** (8 * (0x1B - 3)))

    def test_encode_roundtrip_and_known(self):
        self.assertEqual(encode_compact(POW_LIMIT_MAINNET), BITS_MAINNET_LIMIT)
        self.assertEqual(encode_compact(POW_LIMIT_REGTEST), BITS_REGTEST_LIMIT)
        self.assertEqual(encode_compact(0x80), 0x02008000)       # sign bit forces a padding byte
        self.assertEqual(encode_compact(0), 0)
        self.assertEqual(encode_compact(0x12), 0x01120000)
        for bits in (0x1D00FFFF, 0x1B0404CB, 0x17034219, 0x207FFFFF, 0x1A05DB8B, 0x02008000):
            self.assertEqual(encode_compact(bits_to_target(bits)), bits)

    def test_bits_to_target_rejects_invalid(self):
        for bits in (0, 0x01FEDCBA, 0x04923456, 0xFF123456, 0x00123456):
            with self.subTest(bits=hex(bits)):
                with self.assertRaises(ValueError):
                    bits_to_target(bits)
        for bad in (-1, 2 ** 32, "1d00ffff", 1.5):
            with self.assertRaises(ValueError):
                decode_compact(bad)


class TestByteOrder(unittest.TestCase):
    def test_hash_integer_is_little_endian(self):
        digest = bytes(31) + b"\x01"            # LE value 2^248, displayed as 0100..00
        self.assertEqual(hash_to_int(digest), 1 << 248)
        self.assertEqual(digest_to_display(digest), "01" + "00" * 31)
        digest2 = b"\x01" + bytes(31)            # LE value 1, displayed as 00..0001
        self.assertEqual(hash_to_int(digest2), 1)
        self.assertEqual(digest_to_display(digest2), "00" * 31 + "01")
        self.assertEqual(display_hash_to_int(digest_to_display(digest2)), 1)
        self.assertEqual(display_to_digest(digest_to_display(digest)), digest)

    def test_displayed_looks_small_but_is_not(self):
        # A digest whose RAW hex starts with zeros is NOT a small PoW integer.
        raw = bytes(4) + b"\xff" * 28
        self.assertTrue(raw.hex().startswith("00000000"))
        self.assertGreater(hash_to_int(raw), POW_LIMIT_MAINNET)
        self.assertFalse(check_proof_of_work(raw, BITS_MAINNET_LIMIT))
        # Conversely, a digest ending in zero bytes (displayed with leading zeros) passes.
        ok = b"\xff" * 4 + bytes(28)
        self.assertTrue(digest_to_display(ok).startswith("00" * 28))
        self.assertTrue(check_proof_of_work(ok, BITS_MAINNET_LIMIT))


class TestCheckPow(unittest.TestCase):
    def test_boundary_hash_equal_to_target_passes(self):
        t = bits_to_target(BITS_MAINNET_LIMIT)
        eq = t.to_bytes(32, "little")
        self.assertTrue(check_proof_of_work(eq, BITS_MAINNET_LIMIT))
        self.assertFalse(check_proof_of_work((t + 1).to_bytes(32, "little"), BITS_MAINNET_LIMIT))
        self.assertTrue(check_proof_of_work((t - 1).to_bytes(32, "little"), BITS_MAINNET_LIMIT))

    def test_invalid_bits_always_fail(self):
        zero_hash = bytes(32)
        for bits in (0, 0x01FEDCBA, 0xFF123456, 0x04923456):
            self.assertFalse(check_proof_of_work(zero_hash, bits))

    def test_target_above_pow_limit_fails(self):
        self.assertFalse(check_proof_of_work(bytes(32), 0x1E00FFFF, POW_LIMIT_MAINNET))
        self.assertTrue(check_proof_of_work(bytes(32), 0x1E00FFFF, POW_LIMIT_REGTEST))
        self.assertFalse(check_proof_of_work(bytes(32), 0x2100FFFF + 0x01000000, POW_LIMIT_REGTEST))

    def test_max_hash_vs_max_target(self):
        self.assertFalse(check_proof_of_work(b"\xff" * 32, BITS_REGTEST_LIMIT, POW_LIMIT_REGTEST))
        self.assertEqual(hash_to_int(b"\xff" * 32), MAX_UINT256)
        with self.assertRaises(ValueError):
            hash_to_int(bytes(31))


class TestDifficulty(unittest.TestCase):
    def test_known_difficulties(self):
        self.assertEqual(difficulty_from_bits(0x1D00FFFF), 1.0)
        self.assertAlmostEqual(difficulty_from_bits(0x1B0404CB), 16307.420938523983, places=6)
        self.assertAlmostEqual(difficulty_from_bits(0x207FFFFF), 4.656542373906925e-10, places=20)

    def test_exact_vs_core_formula(self):
        for bits in (0x1D00FFFF, 0x1B0404CB, 0x17034219, 0x207FFFFF):
            self.assertAlmostEqual(difficulty_from_target(bits_to_target(bits)) /
                                   difficulty_from_bits(bits), 1.0, places=4)

    def test_work_and_expected_hashes(self):
        self.assertEqual(block_work(0x1D00FFFF), 0x100010001)         # 4295032833
        self.assertEqual(block_work(0x207FFFFF), 2)
        self.assertAlmostEqual(expected_hashes(bits_to_target(0x1D00FFFF)), 4295032833.0, delta=1)
        with self.assertRaises(ValueError):
            expected_hashes(0)


if __name__ == "__main__":
    unittest.main()
