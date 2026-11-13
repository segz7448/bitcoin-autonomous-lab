"""Regression tests for independent final-verification findings."""
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blockchain.storage import ChainStore
from mining.engine.template import TemplateError, TemplateManager
from tests.test_engine_template import StubRPC


class TestChainStorePathSafety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / "chain.db"

    @unittest.skipUnless(os.name == "posix", "POSIX permissions only")
    def test_new_database_private(self):
        with ChainStore(self.db):
            pass
        self.assertEqual(stat.S_IMODE(self.db.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == "posix", "POSIX permissions only")
    def test_existing_database_restricted_without_losing_data(self):
        with ChainStore(self.db) as store:
            store.record_event("check", "survives")
        os.chmod(self.db, 0o644)
        with ChainStore(self.db) as store:
            self.assertEqual(store.events()[0]["detail"], "survives")
        self.assertEqual(stat.S_IMODE(self.db.stat().st_mode), 0o600)

    @unittest.skipUnless(os.name == "posix", "POSIX symlink semantics")
    def test_existing_symlink_refused_without_touching_target(self):
        victim = self.root / "victim.db"
        with ChainStore(victim) as store:
            store.record_event("check", "unchanged")
        before = victim.read_bytes()
        os.chmod(victim, 0o640)
        self.db.symlink_to(victim)
        with self.assertRaises(ValueError):
            ChainStore(self.db)
        self.assertEqual(victim.read_bytes(), before)
        self.assertEqual(stat.S_IMODE(victim.stat().st_mode), 0o640)

    @unittest.skipUnless(os.name == "posix", "POSIX symlink semantics")
    def test_dangling_symlink_refused_without_creating_target(self):
        victim = self.root / "missing.db"
        self.db.symlink_to(victim)
        with self.assertRaises(ValueError):
            ChainStore(self.db)
        self.assertFalse(victim.exists())

    def test_directory_refused(self):
        with self.assertRaises(ValueError):
            ChainStore(self.root)

    @unittest.skipUnless(os.name == "posix", "POSIX permissions only")
    def test_permission_failure_is_not_hidden(self):
        with patch("blockchain.storage.os.chmod", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                ChainStore(self.db)


class TestImmutableRegtestBoundary(unittest.TestCase):
    def test_nonregtest_override_refused_before_rpc(self):
        for chain in ("main", "test", "testnet4", "signet", None, ""):
            with self.subTest(chain=chain):
                rpc = StubRPC(chain=chain)
                with self.assertRaises(ValueError):
                    TemplateManager(rpc, expected_chain=chain)
                self.assertEqual(rpc.acquisitions, 0)

    def test_reported_nonregtest_chain_refused(self):
        for chain in ("main", "test", "testnet4", "signet", None, ""):
            with self.subTest(chain=chain):
                rpc = StubRPC(chain=chain)
                manager = TemplateManager(rpc, expected_chain="regtest")
                with self.assertRaises(TemplateError):
                    manager.acquire()
                self.assertEqual(rpc.acquisitions, 0)


if __name__ == "__main__":
    unittest.main()
