"""Mine a synthetic low-difficulty block locally and verify the result."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mining.block import (  # noqa: E402
    BlockHeader, build_coinbase_tx, internal_to_display, merkle_root,
)
from mining.miner import mine_header, verify_pow  # noqa: E402

# Regtest genesis difficulty: the largest target the consensus rules allow
# on regtest. Roughly every other hash wins.
REGTEST_BITS = 0x207FFFFF


class TestMining(unittest.TestCase):
    def test_mine_and_verify_low_difficulty_block(self):
        coinbase = build_coinbase_tx(
            height=1,
            value_sats=5_000_000_000,
            script_pubkey=bytes.fromhex("51"),  # OP_TRUE, anyone-can-spend
        )
        self.assertEqual(coinbase.stripped, coinbase.full)  # no witness
        root = internal_to_display(merkle_root([coinbase.txid_internal]))
        header = BlockHeader(
            version=0x20000000,
            prev_hash_display="00" * 32,
            merkle_root_display=root,
            timestamp=1296688602,  # regtest genesis time
            bits=REGTEST_BITS,
            nonce=0,
        )
        result = mine_header(header, max_seconds=30)
        self.assertTrue(result.found, "no nonce found at regtest difficulty")
        header.nonce = result.nonce
        self.assertTrue(verify_pow(header))
        self.assertGreaterEqual(result.hashes, 1)
        self.assertGreater(result.hashrate, 0)

    def test_impossible_target_exhausts_range(self):
        # bits encoding a target of 1: only the all-zero hash wins, which a
        # small scan will never find. Exercises the exhaustion path.
        header = BlockHeader(
            version=1, prev_hash_display="00" * 32,
            merkle_root_display="00" * 32, timestamp=0,
            bits=0x01010000, nonce=0,
        )
        result = mine_header(header, max_nonces=1000)
        self.assertFalse(result.found)
        self.assertEqual(result.hashes, 1000)


if __name__ == "__main__":
    unittest.main()
