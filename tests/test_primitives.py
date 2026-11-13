"""Proof-of-work verification against real Bitcoin blocks.

Reconstructs the 80-byte header of actual mainnet blocks from their
published fields, recomputes the double-SHA-256 block hash, and checks:
  1. the recomputed hash equals the block's well-known block hash, and
  2. the hash is below the target encoded in the header's bits field.

Block 125552 constants were fetched from the Blockstream Esplora API
(https://blockstream.info/api/block-height/125552) on 2026-11-13 and are
embedded here so the test needs no network.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain.primitives import (  # noqa: E402
    BlockHeader, bits_to_target, target_to_bits,
)

GENESIS = {
    "hash": "000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f",
    "version": 1,
    "prev": "00" * 32,
    # Single-tx block: merkle root equals the genesis coinbase txid.
    "merkle": "4a5e1e4baab89f3a32518a88c31bc87f618f76673e2cc77ab2127b7afdeda33b",
    "time": 1231006505,
    "bits": 0x1D00FFFF,
    "nonce": 2083236893,
}

BLOCK_125552 = {
    "hash": "00000000000000001e8d6829a8a21adc5d38d0a473b144b6765798e61f98bd1d",
    "version": 1,
    "prev": "00000000000008a3a41b85b8b29ad444def299fee21793cd8b9e567eab02cd81",
    "merkle": "2b12fcf1b09288fcaff797d71e950e71ae42b91e8bdb2304758dfcffc2b620e3",
    "time": 1305998791,
    "bits": 440711666,  # 0x1a44b9d2
    "nonce": 2504433986,
}


class TestKnownBlocks(unittest.TestCase):
    def _check(self, fields):
        header = BlockHeader(
            version=fields["version"],
            prev_hash_display=fields["prev"],
            merkle_root_display=fields["merkle"],
            timestamp=fields["time"],
            bits=fields["bits"],
            nonce=fields["nonce"],
        )
        self.assertEqual(len(header.serialize()), 80)
        self.assertEqual(header.hash_display(), fields["hash"],
                         "recomputed block hash mismatch")
        self.assertTrue(header.meets_target(), "hash not below target")

    def test_genesis_block(self):
        self._check(GENESIS)

    def test_block_125552(self):
        self._check(BLOCK_125552)

    def test_bits_roundtrip(self):
        for bits in (0x1D00FFFF, 0x1A44B9D2, 0x207FFFFF, 0x17034219):
            with self.subTest(bits=hex(bits)):
                self.assertEqual(target_to_bits(bits_to_target(bits)), bits)


if __name__ == "__main__":
    unittest.main()
