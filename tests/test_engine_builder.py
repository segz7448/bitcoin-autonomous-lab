"""TASK 005 Phase 3: candidate block construction tests."""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain.primitives import (  # noqa: E402
    internal_to_display, merkle_root, sha256d_fast,
)
from mining.block import build_coinbase_tx  # noqa: E402
from mining.engine.builder import (  # noqa: E402
    BuildError, build_candidate, select_transactions, split_witness,
)
from mining.engine.template import parse_template, subsidy_at  # noqa: E402

from tests.test_engine_template import make_template  # noqa: E402

BITCOIND = os.environ.get("BAL_BITCOIND") or shutil.which("bitcoind")

PAYOUT = bytes.fromhex("51")  # OP_TRUE, anyone-can-spend (regtest only)


def synthetic_tx(seed: int, witness: bool = False) -> dict:
    """A genuine transaction whose txid/wtxid we can compute independently."""
    built = build_coinbase_tx(
        height=seed + 1, value_sats=0, script_pubkey=PAYOUT,
        extranonce=f"tx{seed}".encode(),
        witness_commitment=b"\x11" * 32 if witness else None,
    )
    entry = {
        "txid": internal_to_display(sha256d_fast(built.stripped)),
        "data": built.full.hex(),
        "fee": 1_000 * (seed + 1),
        "depends": [],
        "sigops": 1,
        "weight": 4 * len(built.stripped),
    }
    if witness:
        entry["hash"] = internal_to_display(sha256d_fast(built.full))
    return entry


class TestSplitWitness(unittest.TestCase):
    def test_stripped_roundtrip(self):
        for witness in (False, True):
            tx = synthetic_tx(1, witness=witness)
            stripped, is_witness = split_witness(bytes.fromhex(tx["data"]))
            self.assertEqual(is_witness, witness)
            self.assertEqual(internal_to_display(sha256d_fast(stripped)),
                             tx["txid"])

    def test_truncated_fails_closed(self):
        tx = synthetic_tx(2, witness=True)
        with self.assertRaises(BuildError):
            split_witness(bytes.fromhex(tx["data"])[:-3])

    def test_trailing_bytes_fail_closed(self):
        tx = synthetic_tx(3)
        with self.assertRaises(BuildError):
            split_witness(bytes.fromhex(tx["data"]) + b"\x00")


class TestBuildCandidate(unittest.TestCase):
    def test_coinbase_only_block(self):
        template = parse_template(make_template())
        candidate = build_candidate(template, PAYOUT)
        self.assertEqual(candidate.height, 1)
        self.assertEqual(candidate.fees, 0)
        self.assertEqual(candidate.coinbase_value, subsidy_at(1))
        self.assertEqual(len(candidate.txs), 1)
        self.assertEqual(len(candidate.header.serialize()), 80)
        # Merkle root of a lone coinbase is the coinbase txid.
        self.assertEqual(
            internal_to_display(merkle_root([candidate.coinbase.txid_internal])),
            internal_to_display(candidate.coinbase.txid_internal),
        )
        # Full serialization: 80-byte header, varint count, transactions.
        blob = candidate.serialize()
        self.assertEqual(blob[:80], candidate.header.serialize())
        self.assertEqual(blob[80], 1)

    def test_block_with_transactions_and_fee_accounting(self):
        txs = [synthetic_tx(1), synthetic_tx(2, witness=True)]
        template = parse_template(make_template(
            transactions=txs,
            coinbasevalue=subsidy_at(1) + 5_000,
        ))
        candidate = build_candidate(template, PAYOUT)
        self.assertEqual(candidate.fees, 5_000)
        self.assertEqual(candidate.coinbase_value, subsidy_at(1) + 5_000)
        self.assertEqual(candidate.selected_txids, [t["txid"] for t in txs])
        self.assertEqual(candidate.witness_tx_count, 1)
        self.assertEqual(len(candidate.txs), 3)
        # Witness commitment embedded in the coinbase.
        self.assertIn(bytes.fromhex("aa21a9ed"), candidate.coinbase.full)

    def test_txid_mismatch_fails_closed(self):
        bad = synthetic_tx(1)
        bad["data"] = "00" + bad["data"][2:]  # corrupt the version byte
        template = parse_template(make_template(
            transactions=[bad], coinbasevalue=subsidy_at(1) + 1_000))
        with self.assertRaises(BuildError):
            build_candidate(template, PAYOUT)

    def test_false_witness_claim_fails_closed(self):
        bad = synthetic_tx(1)
        bad["hash"] = "ab" * 32  # claims witness, data has none
        template = parse_template(make_template(
            transactions=[bad], coinbasevalue=subsidy_at(1) + 1_000))
        with self.assertRaises(BuildError):
            build_candidate(template, PAYOUT)

    def test_commitment_disagreement_fails_closed(self):
        txs = [synthetic_tx(1, witness=True)]
        template = parse_template(make_template(
            transactions=txs,
            coinbasevalue=subsidy_at(1) + 1_000,
            default_witness_commitment="6a24aa21a9ed" + "ff" * 32,
        ))
        with self.assertRaises(BuildError):
            build_candidate(template, PAYOUT)

    def test_selection_respects_limits_and_dependencies(self):
        tx1 = synthetic_tx(1)
        tx2 = synthetic_tx(2)
        tx2["depends"] = [1]
        # Weight limit only admits the coinbase reserve + nothing else.
        template = parse_template(make_template(
            transactions=[tx1, tx2],
            coinbasevalue=subsidy_at(1) + 3_000,
            weightlimit=1_000,
        ))
        selected, fees = select_transactions(template)
        self.assertEqual(selected, [])
        self.assertEqual(fees, 0)

    def test_extranonce_changes_merkle_root(self):
        template = parse_template(make_template())
        base = build_candidate(template, PAYOUT)
        bumped = base.with_extranonce(1)
        self.assertNotEqual(base.serialize(), bumped.serialize())
        self.assertNotEqual(base.header.serialize(), bumped.header.serialize())
        self.assertEqual(bumped.height, base.height)
        other = base.with_extranonce(2)
        self.assertNotEqual(bumped.header.serialize(), other.header.serialize())

    def test_timestamp_rules(self):
        template = parse_template(make_template())
        base = build_candidate(template, PAYOUT)
        with self.assertRaises(BuildError):
            base.with_timestamp(template.mintime - 1)
        later = base.with_timestamp(template.mintime + 600)
        self.assertEqual(later.header.timestamp, template.mintime + 600)

    def test_coinbase_never_exceeds_template_permission(self):
        tx = synthetic_tx(1)  # fee 2000
        tx["fee"] = 2_000
        template = parse_template(make_template(
            transactions=[tx], coinbasevalue=subsidy_at(1) + 1))
        with self.assertRaises(BuildError):
            build_candidate(template, PAYOUT)


@unittest.skipUnless(BITCOIND, "bitcoind not available; set BAL_BITCOIND")
class TestLiveCandidateConsensus(unittest.TestCase):
    """Build a candidate from a live template and prove Core accepts it."""

    RPC_PORT = 18447

    def setUp(self):
        from node.node_manager import NodeConfig, NodeManager
        self.datadir = tempfile.mkdtemp(prefix="bal-cand-")
        self.manager = NodeManager(NodeConfig(
            bitcoind=BITCOIND, datadir=self.datadir, rpc_port=self.RPC_PORT,
        ))
        self.rpc = self.manager.start()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        try:
            self.manager.stop()
        except Exception:
            pass
        shutil.rmtree(self.datadir, ignore_errors=True)

    def test_constructed_block_accepted_by_core(self):
        from mining.engine.template import TemplateManager
        from mining.miner import mine_header, verify_pow

        manager = TemplateManager(self.rpc)
        template = manager.acquire()
        self.rpc.create_wallet("bal")
        address = self.rpc.get_new_address()
        script = bytes.fromhex(self.rpc.get_address_info(address)["scriptPubKey"])

        candidate = build_candidate(template, script)
        self.assertEqual(candidate.coinbase_value, template.coinbase_value)

        result = mine_header(candidate.header, max_seconds=30)
        self.assertTrue(result.found, "no nonce at regtest difficulty")
        candidate.header.nonce = result.nonce
        self.assertTrue(verify_pow(candidate.header))

        reject = self.rpc.submit_block(candidate.block_hex())
        self.assertIsNone(reject, f"Core rejected constructed block: {reject}")
        committed = self.rpc.get_block(candidate.block_hash_display())
        self.assertGreaterEqual(committed["confirmations"], 1)
        self.assertEqual(committed["height"], template.height)
        self.assertEqual(self.rpc.get_block_count(), template.height)


if __name__ == "__main__":
    unittest.main()
