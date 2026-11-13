"""Mining database permission hardening tests (pre-TASK 007 corrections).

The mining statistics database holds the full operational history of the
agent; like the blockchain chain store, it must be owner-only (0600) on
supported Unix-like systems, both when first created and when an existing
file is reopened.
"""

import os
import shutil
import stat
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mining.engine.stats import MiningStatsStore  # noqa: E402

POSIX = os.name == "posix"

_SESSION = {
    "session_id": "perm-test", "started_at": "t0", "finished_at": "t1",
    "height": 1, "prev_hash": "p", "block_hash": "b", "seconds": 1.0,
    "hashes": 10, "hashrate_avg": 10.0, "hashrate_peak": 10.0,
    "backend": "cpu", "batches": 1, "nonce": 0, "extranonce_counter": 0,
    "submit_result": "", "accepted": 1, "coinbase_value": 0, "fees": 0,
    "error": None,
}


class TestMiningStatsPermissions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bal-perms-")
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _mode(self, path):
        return stat.S_IMODE(os.stat(path).st_mode)

    def test_parent_directory_created_safely(self):
        db = os.path.join(self.tmp, "nested", "dir", "mining.db")
        with MiningStatsStore(db):
            pass
        self.assertTrue(os.path.isfile(db))

    @unittest.skipUnless(POSIX, "POSIX file permissions only")
    def test_new_database_is_owner_only(self):
        db = os.path.join(self.tmp, "mining.db")
        with MiningStatsStore(db):
            pass
        self.assertEqual(self._mode(db), 0o600)

    @unittest.skipUnless(POSIX, "POSIX file permissions only")
    def test_existing_permissive_database_is_restricted(self):
        db = os.path.join(self.tmp, "mining.db")
        with MiningStatsStore(db):
            pass
        os.chmod(db, 0o644)  # simulate a database left permissive
        with MiningStatsStore(db):
            pass
        self.assertEqual(self._mode(db), 0o600)

    @unittest.skipUnless(POSIX, "symlink semantics are POSIX")
    def test_symlink_database_path_refused_not_clobbered(self):
        victim = os.path.join(self.tmp, "victim.db")
        with open(victim, "w") as fh:
            fh.write("IMPORTANT\n")
        link = os.path.join(self.tmp, "mining.db")
        os.symlink(victim, link)
        with self.assertRaises(ValueError):
            MiningStatsStore(link)
        with open(victim) as fh:
            self.assertEqual(fh.read(), "IMPORTANT\n")
        # Dangling symlink: also refused, target not created.
        dangling = os.path.join(self.tmp, "gone.db")
        link2 = os.path.join(self.tmp, "mining2.db")
        os.symlink(dangling, link2)
        with self.assertRaises(ValueError):
            MiningStatsStore(link2)
        self.assertFalse(os.path.exists(dangling))

    @unittest.skipUnless(POSIX, "symlink semantics are POSIX")
    def test_non_regular_database_path_refused(self):
        with self.assertRaises(ValueError):
            MiningStatsStore(self.tmp)  # a directory, not a file

    @unittest.skipUnless(POSIX, "POSIX file permissions only")
    def test_restriction_never_weakens_and_preserves_data(self):
        db = os.path.join(self.tmp, "mining.db")
        with MiningStatsStore(db) as store:
            store.record_session(dict(_SESSION))
        os.chmod(db, 0o640)
        with MiningStatsStore(db) as reopened:
            history = reopened.history()
        self.assertEqual(self._mode(db), 0o600)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["session_id"], "perm-test")
        self.assertEqual(history[0]["accepted"], 1)


if __name__ == "__main__":
    unittest.main()
