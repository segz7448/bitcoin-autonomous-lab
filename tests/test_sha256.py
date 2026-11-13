"""Verify the pure-Python SHA-256 against NIST/FIPS vectors and hashlib."""

import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain import sha256 as slow_sha  # noqa: E402


class TestSHA256Vectors(unittest.TestCase):
    # FIPS 180-4 / NIST CAVP example vectors.
    VECTORS = [
        (
            b"",
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        ),
        (
            b"abc",
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
        ),
        (
            b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
            "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
        ),
    ]

    def test_nist_vectors(self):
        for message, expected in self.VECTORS:
            with self.subTest(message=message[:16]):
                self.assertEqual(slow_sha.sha256(message).hex(), expected)

    def test_matches_hashlib_across_lengths(self):
        # Every padding boundary: lengths 0..129 cover all padding branches.
        rng = 0x5EED
        for length in range(130):
            data = bytes((rng := (rng * 1103515245 + 12345) & 0x7FFFFFFF) & 0xFF
                         for _ in range(length))
            self.assertEqual(
                slow_sha.sha256(data), hashlib.sha256(data).digest(),
                f"mismatch at length {length}",
            )

    def test_sha256d_matches_hashlib(self):
        data = bytes(range(256)) * 3
        expected = hashlib.sha256(hashlib.sha256(data).digest()).digest()
        self.assertEqual(slow_sha.sha256d(data), expected)


if __name__ == "__main__":
    unittest.main()
