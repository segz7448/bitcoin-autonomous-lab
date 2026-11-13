"""TASK 005 Phase 2: mining-template acquisition and staleness tests."""

import copy
import time
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mining.engine.template import (  # noqa: E402
    MiningTemplate, TemplateError, TemplateManager, parse_template,
    subsidy_at,
)
from mining.pow.target import POW_LIMIT_REGTEST  # noqa: E402

BITCOIND = os.environ.get("BAL_BITCOIND") or shutil.which("bitcoind")

GENESIS = "0f9188f13cb7b2c71f2a335e3a4fc328bf5beb436012afca590b1a11466e2206"


def make_template(**overrides) -> dict:
    template = {
        "capabilities": ["proposal"],
        "version": 0x20000000,
        "rules": ["segwit"],
        "vbavailable": {},
        "vbrequired": 0,
        "previousblockhash": GENESIS,
        "transactions": [],
        "coinbaseaux": {"flags": ""},
        "coinbasevalue": 5_000_000_000,
        "longpollid": "lp1",
        "target": "7fffff" + "00" * 29,
        "mintime": 1_700_000_000,
        "mutable": ["time", "transactions", "prevblock"],
        "noncerange": "00000000ffffffff",
        "sigoplimit": 80_000,
        "sizelimit": 4_000_000,
        "weightlimit": 4_000_000,
        "curtime": 1_700_000_000,
        "bits": "207fffff",
        "height": 1,
        "expires": 120,
    }
    template.update(overrides)
    return template


def make_tx(position: int, fee: int = 1_000, depends=None, witness=False) -> dict:
    txid = f"{position:064x}"
    tx = {
        "txid": txid,
        "data": "0200" + "00" * 40,
        "fee": fee,
        "depends": depends or [],
        "sigops": 2,
        "weight": 400,
    }
    if witness:
        tx["hash"] = f"{position + 1000:064x}"
    return tx


class StubRPC:
    """Programmable stand-in for BitcoinRPC; no transport involved."""

    def __init__(self, template=None, chain="regtest", best=GENESIS, blocks=0):
        self.template = template if template is not None else make_template()
        self.chain = chain
        self.best = best
        self.blocks = blocks
        self.acquisitions = 0

    def get_blockchain_info(self):
        return {"chain": self.chain, "blocks": self.blocks}

    def get_block_template(self):
        self.acquisitions += 1
        return copy.deepcopy(self.template)

    def get_best_block_hash(self):
        return self.best


class TestSubsidy(unittest.TestCase):
    def test_halving_schedule(self):
        self.assertEqual(subsidy_at(0), 5_000_000_000)
        self.assertEqual(subsidy_at(209_999), 5_000_000_000)
        self.assertEqual(subsidy_at(210_000), 2_500_000_000)
        self.assertEqual(subsidy_at(210_000 * 64), 0)


class TestParseTemplate(unittest.TestCase):
    def test_minimal_template_ok(self):
        t = parse_template(make_template())
        self.assertEqual(t.previous_block_hash, GENESIS)
        self.assertEqual(t.version, 0x20000000)
        self.assertEqual(t.height, 1)
        self.assertEqual(t.bits, 0x207FFFFF)
        self.assertEqual(t.target, POW_LIMIT_REGTEST)
        self.assertEqual(t.tx_count, 0)
        self.assertEqual(t.total_fees, 0)
        self.assertEqual(t.coinbase_value, 5_000_000_000)
        self.assertEqual(t.expires_at, 1_700_000_000 + 120)
        self.assertFalse(t.has_witness_transactions)

    def test_transactions_fees_dependencies(self):
        t = parse_template(make_template(transactions=[
            make_tx(1, fee=1_000),
            make_tx(2, fee=2_500, depends=[1], witness=True),
        ], coinbasevalue=5_000_003_500))
        self.assertEqual(t.tx_count, 2)
        self.assertEqual(t.total_fees, 3_500)
        self.assertEqual(t.transactions[1].depends, (1,))
        self.assertTrue(t.transactions[1].has_witness)
        self.assertEqual(t.total_tx_weight, 800)

    def test_dependency_must_reference_earlier_tx(self):
        with self.assertRaises(TemplateError):
            parse_template(make_template(
                transactions=[make_tx(1), make_tx(2, depends=[2])],
                coinbasevalue=5_000_002_000,
            ))

    def test_missing_required_field_fails(self):
        for field_name in ("previousblockhash", "version", "height", "bits",
                           "curtime", "mintime", "coinbasevalue",
                           "transactions"):
            bad = make_template()
            bad.pop(field_name)
            with self.assertRaises(TemplateError, msg=field_name):
                parse_template(bad)

    def test_bad_bits_fails(self):
        with self.assertRaises(TemplateError):
            parse_template(make_template(bits="zzzzzzzz"))
        with self.assertRaises(TemplateError):  # zero target
            parse_template(make_template(bits="00000000"))
        with self.assertRaises(TemplateError):  # negative target
            parse_template(make_template(bits="01808000"))

    def test_target_above_regtest_limit_fails(self):
        # One step above the regtest pow limit mantissa at the same size.
        with self.assertRaises(TemplateError):
            parse_template(make_template(bits="21800000"))

    def test_coinbase_never_exceeds_subsidy_plus_fees(self):
        with self.assertRaises(TemplateError):
            parse_template(make_template(coinbasevalue=5_000_000_001))
        # Exactly subsidy + supplied fees is permitted.
        t = parse_template(make_template(
            transactions=[make_tx(1, fee=1)],
            coinbasevalue=5_000_000_001,
        ))
        self.assertEqual(t.coinbase_value, 5_000_000_001)

    def test_missing_tx_fee_fails(self):
        tx = make_tx(1)
        tx.pop("fee")
        with self.assertRaises(TemplateError):
            parse_template(make_template(transactions=[tx]))

    def test_version_range_enforced(self):
        with self.assertRaises(TemplateError):
            parse_template(make_template(version=2 ** 31))
        with self.assertRaises(TemplateError):
            parse_template(make_template(version=True))

    def test_mintime_after_curtime_fails(self):
        with self.assertRaises(TemplateError):
            parse_template(make_template(mintime=1_700_000_001))

    def test_witness_commitment_validated(self):
        t = parse_template(make_template(
            default_witness_commitment="6a24aa21a9ed" + "00" * 32))
        self.assertTrue(t.default_witness_commitment.startswith("6a24aa21a9ed"))
        with self.assertRaises(TemplateError):
            parse_template(make_template(default_witness_commitment="zz"))


class TestTemplateManager(unittest.TestCase):
    def test_acquire_and_fresh_template_not_stale(self):
        rpc = StubRPC()
        manager = TemplateManager(rpc)
        template = manager.acquire()
        self.assertIsInstance(template, MiningTemplate)
        self.assertEqual(manager.staleness_reasons(template,
                                                   now=template.curtime), [])
        self.assertFalse(manager.is_stale(template, now=template.curtime))

    def test_refuses_non_regtest(self):
        manager = TemplateManager(StubRPC(chain="main"))
        with self.assertRaises(TemplateError):
            manager.acquire()

    def test_stale_on_tip_change(self):
        rpc = StubRPC()
        manager = TemplateManager(rpc)
        template = manager.acquire()
        rpc.best = "11" * 32
        self.assertEqual(manager.staleness_reasons(template,
                                                   now=template.curtime),
                         ["blockchain tip changed"])
        self.assertTrue(manager.is_stale(template, now=template.curtime))

    def test_stale_on_expiry(self):
        rpc = StubRPC()
        manager = TemplateManager(rpc)
        template = manager.acquire()
        self.assertEqual(
            manager.staleness_reasons(template, now=template.expires_at),
            ["template expired"])

    def test_refresh_only_when_stale(self):
        # refresh() judges expiry against the real clock, so this template
        # must be current.
        now = int(time.time())
        rpc = StubRPC(template=make_template(curtime=now, mintime=now - 10))
        manager = TemplateManager(rpc)
        template = manager.acquire()
        same = manager.refresh(template)
        self.assertIs(same, template)
        self.assertEqual(rpc.acquisitions, 1)
        rpc.best = "22" * 32
        fresh = manager.refresh(template)
        self.assertIsNot(fresh, template)
        self.assertEqual(rpc.acquisitions, 2)


@unittest.skipUnless(BITCOIND, "bitcoind not available; set BAL_BITCOIND")
class TestLiveTemplateAcquisition(unittest.TestCase):
    """Real getblocktemplate against a disposable regtest node."""

    RPC_PORT = 18446

    def setUp(self):
        from node.node_manager import NodeConfig, NodeManager
        self.datadir = tempfile.mkdtemp(prefix="bal-tmpl-")
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

    def test_acquire_and_staleness_against_live_node(self):
        manager = TemplateManager(self.rpc)
        template = manager.acquire()
        self.assertEqual(template.height, self.rpc.get_block_count() + 1)
        self.assertEqual(template.previous_block_hash,
                         self.rpc.get_best_block_hash())
        self.assertFalse(manager.is_stale(template))

        # Advance the tip with Core's own generator (an independent testing
        # tool only; the project's engine is not involved here).
        self.rpc.create_wallet("bal")
        address = self.rpc.get_new_address()
        self.rpc.generate_to_address(1, address)

        self.assertTrue(manager.is_stale(template))
        self.assertIn("blockchain tip changed",
                      manager.staleness_reasons(template))
        fresh = manager.refresh(template)
        self.assertEqual(fresh.height, template.height + 1)
        self.assertEqual(fresh.previous_block_hash,
                         self.rpc.get_best_block_hash())
        self.assertFalse(manager.is_stale(fresh))


if __name__ == "__main__":
    unittest.main()
