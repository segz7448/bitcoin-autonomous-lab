"""Chain monitoring and independent verification logic with a fake node."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain.monitor import ChainMonitor  # noqa: E402
from blockchain.primitives import BlockHeader  # noqa: E402

REGTEST_BITS = 0x207FFFFF


def _mined_header(prev_hash: str = "00" * 32,
                  timestamp: int = 1296688602) -> BlockHeader:
    """A real low-difficulty header (regtest target), nonce actually scanned."""
    header = BlockHeader(
        version=0x20000000, prev_hash_display=prev_hash,
        merkle_root_display="11" * 32, timestamp=timestamp,
        bits=REGTEST_BITS, nonce=0,
    )
    for nonce in range(1000):
        header.nonce = nonce
        if header.meets_target():
            return header
    raise AssertionError("no nonce found at regtest difficulty")


def _mined_chain(length: int) -> list:
    """A linked chain of distinct headers, each mined at regtest difficulty."""
    chain = [_mined_header()]
    for i in range(1, length):
        chain.append(_mined_header(chain[-1].hash_display(), 1296688602 + i * 150))
    return chain


def _block_json(header: BlockHeader, height: int) -> dict:
    return {
        "hash": header.hash_display(),
        "height": height,
        "version": header.version,
        "previousblockhash": header.prev_hash_display,
        "merkleroot": header.merkle_root_display,
        "time": header.timestamp,
        "bits": f"{header.bits:08x}",
        "nonce": header.nonce,
        "nTx": 1,
        "confirmations": 1,
    }


class _FakeRPC:
    """Canned node holding a short fake chain of real headers."""

    def __init__(self):
        self.blocks = _mined_chain(3)
        self.chain_json = {
            "chain": "regtest", "blocks": 2, "headers": 2,
            "bestblockhash": self.blocks[-1].hash_display(),
            "difficulty": 4.656542373906925e-10, "mediantime": 1296688602,
            "verificationprogress": 1.0,
        }

    # blockchain queries
    def get_blockchain_info(self):
        return self.chain_json

    def get_block_count(self):
        return self.chain_json["blocks"]

    def get_block(self, block_hash, verbosity=1):
        for i, header in enumerate(self.blocks):
            if header.hash_display() == block_hash:
                return _block_json(header, i)
        raise AssertionError(f"fake node does not know {block_hash}")

    def get_block_hash(self, height):
        return self.blocks[height].hash_display()

    def get_best_block_hash(self):
        return self.chain_json["bestblockhash"]

    # network / mempool
    def get_network_info(self):
        return {"connections": 0}

    def get_mempool_info(self):
        return {"size": 0}

    def uptime(self):
        return 42

    # generation
    def generate_to_address(self, nblocks, address, maxtries=1_000_000):
        out = []
        for _ in range(nblocks):
            header = _mined_header(self.blocks[-1].hash_display(),
                                   1296688602 + len(self.blocks) * 150)
            self.blocks.append(header)
            out.append(header.hash_display())
        self.chain_json["blocks"] = len(self.blocks) - 1
        self.chain_json["bestblockhash"] = self.blocks[-1].hash_display()
        return out


class TestSnapshot(unittest.TestCase):
    def test_snapshot_fields(self):
        status = ChainMonitor(_FakeRPC()).snapshot()
        self.assertEqual(status.chain, "regtest")
        self.assertEqual(status.blocks, 2)
        self.assertEqual(status.mempool_size, 0)
        self.assertEqual(status.connections, 0)
        self.assertEqual(status.node_uptime_s, 42)


class TestVerifyBlock(unittest.TestCase):
    def test_real_header_verifies(self):
        monitor = ChainMonitor(_FakeRPC())
        report = monitor.verify_tip()
        self.assertTrue(report.ok)
        self.assertTrue(report.hash_recomputed)
        self.assertTrue(report.pow_meets_target)
        self.assertEqual(report.height, 2)

    def test_tampered_field_fails(self):
        rpc = _FakeRPC()
        # Corrupt one field: the recomputed hash must no longer match.
        original_get_block = rpc.get_block

        def tampered(block_hash, verbosity=1):
            block = original_get_block(block_hash)
            block["merkleroot"] = "22" * 32
            return block

        rpc.get_block = tampered
        report = ChainMonitor(rpc).verify_tip()
        self.assertFalse(report.hash_recomputed)
        self.assertFalse(report.ok)


class TestGenerateAndVerify(unittest.TestCase):
    def test_generate_two_blocks(self):
        monitor = ChainMonitor(_FakeRPC())
        reports = monitor.generate_and_verify(2, "bcrt1qfake")
        self.assertEqual(len(reports), 2)
        self.assertTrue(all(r.ok for r in reports))
        self.assertEqual([r.height for r in reports], [3, 4])

    def test_wrong_count_raises(self):
        rpc = _FakeRPC()
        original = rpc.generate_to_address

        def short(nblocks, address, maxtries=1_000_000):
            return original(nblocks, address)[:-1]

        rpc.generate_to_address = short
        with self.assertRaises(RuntimeError):
            ChainMonitor(rpc).generate_and_verify(2, "bcrt1qfake")


if __name__ == "__main__":
    unittest.main()
