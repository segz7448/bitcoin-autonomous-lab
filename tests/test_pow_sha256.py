"""SHA-256 / double SHA-256 correctness (no performance measurement here)."""
import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import hashlib, random

from mining.pow.sha256 import SHA256, sha256, sha256_hex
from mining.pow.double_sha256 import double_sha256, double_sha256_fast, double_sha256_hex

# FIPS 180-4 / NIST CAVP example messages.
VECTORS = [
    (b"", "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"),
    (b"abc", "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"),
    (b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
     "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1"),
    (b"abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmnhijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu",
     "cf5b16a778af8380036ce59e7b0492370b249b11e8f07a51afac45037afee9d1"),
    (b"a" * 1_000_000, "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0"),
]


class TestSha256(unittest.TestCase):
    def test_standard_vectors(self):
        for msg, want in VECTORS:
            with self.subTest(len=len(msg)):
                self.assertEqual(sha256_hex(msg), want)
                self.assertEqual(sha256(msg).hex(), want)

    def test_padding_boundaries_against_hashlib(self):
        # Every length around the 55/56/63/64/119/120 byte padding edges.
        for n in list(range(0, 200)) + [255, 256, 1023, 1024, 4095]:
            data = bytes((i * 31 + n) % 256 for i in range(n))
            self.assertEqual(sha256(data), hashlib.sha256(data).digest(), n)

    def test_random_inputs_against_hashlib(self):
        rng = random.Random(1234)  # deterministic
        for _ in range(300):
            data = rng.randbytes(rng.randrange(0, 600))
            self.assertEqual(sha256(data), hashlib.sha256(data).digest())

    def test_streaming_equals_oneshot(self):
        data = bytes(range(256)) * 5
        for split in (0, 1, 63, 64, 65, 500, len(data)):
            h = SHA256()
            h.update(data[:split]).update(data[split:])
            self.assertEqual(h.digest(), hashlib.sha256(data).digest())
        h = SHA256(b"abc")
        c = h.copy()
        c.update(b"def")
        self.assertEqual(h.hexdigest(), sha256_hex(b"abc"))
        self.assertEqual(c.hexdigest(), sha256_hex(b"abcdef"))

    def test_digest_is_non_destructive_and_32_bytes(self):
        h = SHA256(b"x")
        self.assertEqual(h.digest(), h.digest())
        self.assertEqual(len(h.digest()), 32)

    def test_accepts_bytes_like_rejects_str(self):
        self.assertEqual(sha256(bytearray(b"abc")), sha256(b"abc"))
        self.assertEqual(sha256(memoryview(b"abc")), sha256(b"abc"))
        with self.assertRaises(TypeError):
            sha256("abc")


class TestDoubleSha256(unittest.TestCase):
    def test_definition(self):
        for msg in (b"", b"abc", b"hello", bytes(80)):
            self.assertEqual(double_sha256(msg), sha256(sha256(msg)))
            self.assertEqual(double_sha256(msg), hashlib.sha256(hashlib.sha256(msg).digest()).digest())
            self.assertEqual(double_sha256(msg), double_sha256_fast(msg))

    def test_known_vectors(self):
        # SHA256d("") and SHA256d("hello") - published values.
        self.assertEqual(double_sha256_hex(b""),
                         "5df6e0e2761359d30a8275058e299fcc0381534545f55cf43e41983f5d4c9456")
        self.assertEqual(double_sha256_hex(b"hello"),
                         "9595c9df90075148eb06860365df33584b75bff782a510c6cd4883a419833d50")


if __name__ == "__main__":
    unittest.main()
