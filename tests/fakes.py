"""Shared fake-RPC infrastructure for Intelligence Engine tests.

The fake node serves real mined regtest headers (built with the project's
own BlockHeader and nonce scanning), so verification logic in the modules
under test runs against genuine hashes, merkle roots and targets - only
the transport is faked.
"""

import os
import sys
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blockchain.primitives import BlockHeader, display_to_internal, merkle_root  # noqa: E402
from node.rpc_client import RPCError  # noqa: E402

REGTEST_BITS = 0x207FFFFF


def mined_header(prev_hash="00" * 32, timestamp=1296688602,
                 merkle="00" * 32) -> BlockHeader:
    header = BlockHeader(
        version=0x20000000, prev_hash_display=prev_hash,
        merkle_root_display=merkle, timestamp=timestamp,
        bits=REGTEST_BITS, nonce=0,
    )
    for nonce in range(100000):
        header.nonce = nonce
        if header.meets_target():
            return header
    raise AssertionError("no nonce found at regtest difficulty")


def make_block(prev: dict | None, height: int, txids: list[str],
               timestamp: int = 1296688602) -> dict:
    """A getblock(verbosity=1)-shaped block with a genuinely mined header."""
    from blockchain.primitives import internal_to_display
    root = internal_to_display(
        merkle_root([display_to_internal(t) for t in txids]))
    prev_hash = prev["hash"] if prev else "00" * 32
    header = mined_header(prev_hash, timestamp + height * 150, root)
    return {
        "hash": header.hash_display(),
        "height": height,
        "version": header.version,
        "previousblockhash": prev_hash,
        "merkleroot": root,
        "time": header.timestamp,
        "mediantime": header.timestamp,
        "bits": f"{REGTEST_BITS:08x}",
        "nonce": header.nonce,
        "difficulty": 4.617e-10,
        "size": 200 + 100 * len(txids),
        "strippedsize": 190 + 100 * len(txids),
        "weight": 800 + 400 * len(txids),
        "nTx": len(txids),
        "confirmations": 1,
        "tx": list(txids),
    }


class FakeRPC:
    """Scriptable fake node with a reorg-capable chain and a mempool."""

    def __init__(self):
        self.blocks: list[dict] = []  # active chain; index == height
        self.orphans: list[dict] = []
        self.mempool: dict[str, dict] = {}
        self.txs: dict[str, dict] = {}  # txid -> raw verbose tx
        self.failures = 0  # next N RPCs raise URLError
        self.calls = 0
        self._tx_counter = 0

    # --- helpers -----------------------------------------------------------
    def _guard(self):
        self.calls += 1
        if self.failures > 0:
            self.failures -= 1
            raise urllib.error.URLError("simulated outage")

    def _new_txids(self, n: int) -> list[str]:
        out = []
        for _ in range(n):
            self._tx_counter += 1
            out.append(f"{self._tx_counter:064x}")
        return out

    def mine(self, n: int = 1, with_txs: bool = False) -> list[str]:
        """Append n blocks to the active chain; returns their hashes."""
        hashes = []
        for _ in range(n):
            height = len(self.blocks)
            txids = self._new_txids(3 if with_txs else 1)
            block = make_block(self.blocks[-1] if self.blocks else None,
                               height, txids)
            self.blocks.append(block)
            hashes.append(block["hash"])
        return hashes

    def invalidate_tip(self) -> str:
        """Force a reorg by dropping the tip (and queueing a replacement)."""
        self.orphans.append(self.blocks.pop())
        return self.orphans[-1]["hash"]

    # --- blockchain RPCs -----------------------------------------------------
    def get_block_count(self) -> int:
        self._guard()
        return len(self.blocks) - 1

    def get_block_hash(self, height: int) -> str:
        self._guard()
        return self.blocks[height]["hash"]

    def get_block(self, block_hash: str, verbosity: int = 1) -> dict:
        self._guard()
        for block in self.blocks:
            if block["hash"] == block_hash:
                if verbosity == 2:
                    return dict(block, tx=[self._verbose_tx(t, block)
                                           for t in block["tx"]])
                return block
        raise RPCError(-5, "Block not found")

    def get_block_header(self, block_hash: str) -> dict:
        block = self.get_block(block_hash, 1)
        return {k: block[k] for k in
                ("hash", "height", "version", "previousblockhash",
                 "merkleroot", "time", "mediantime", "bits", "nonce",
                 "difficulty", "confirmations")}

    def get_best_block_hash(self) -> str:
        self._guard()
        return self.blocks[-1]["hash"]

    def get_blockchain_info(self) -> dict:
        self._guard()
        return {
            "chain": "regtest", "blocks": len(self.blocks) - 1,
            "headers": len(self.blocks) - 1,
            "bestblockhash": self.blocks[-1]["hash"],
            "difficulty": 4.617e-10, "mediantime": self.blocks[-1]["time"],
            "verificationprogress": 1.0,
        }

    def get_chain_tips(self) -> list:
        self._guard()
        tips = [{"height": len(self.blocks) - 1,
                 "hash": self.blocks[-1]["hash"],
                 "branchlen": 0, "status": "active"}]
        for orphan in self.orphans:
            tips.append({"height": orphan["height"], "hash": orphan["hash"],
                         "branchlen": 1, "status": "valid-fork"})
        return tips

    # --- transaction RPCs ------------------------------------------------------
    def _verbose_tx(self, txid: str, block: dict | None = None) -> dict:
        is_coinbase = bool(block) and block["tx"][0] == txid
        tx = {
            "txid": txid, "size": 250, "vsize": 200, "weight": 800,
            "vin": [{"coinbase": "aa", "sequence": 0}] if is_coinbase
            else [{"txid": "ff" * 32, "vout": 0, "sequence": 0xffffffff}],
            "fee": None if is_coinbase else 0.00001,
            "vout": [{"value": 50.0, "n": 0,
                      "scriptPubKey": {"type": "pubkeyhash",
                                       "address": "bcrt1qaddr"}}],
            "confirmations": 1 if block else 0,
        }
        if block:
            tx["blockhash"] = block["hash"]
        if not is_coinbase:
            tx["fee"] = 0.00001
        return tx

    def get_raw_transaction(self, txid: str, verbose: bool = True) -> dict:
        self._guard()
        if txid in self.txs:
            return self.txs[txid]
        if txid in self.mempool:
            return self._verbose_tx(txid)
        raise RPCError(-5, "No such mempool or blockchain transaction. "
                       "Use gettransaction for wallet transactions.")

    def decode_raw_transaction(self, tx_hex: str) -> dict:
        self._guard()
        return self._verbose_tx("ab" * 32)

    def get_mempool_info(self) -> dict:
        self._guard()
        return {"size": len(self.mempool), "bytes": 200 * len(self.mempool),
                "usage": 1024 * len(self.mempool),
                "total_fee": sum(e["fees"]["base"]
                                 for e in self.mempool.values()),
                "mempoolminfee": 0.00001}

    def get_raw_mempool(self, verbose: bool = False):
        self._guard()
        if verbose:
            return dict(self.mempool)
        return list(self.mempool)

    def get_mempool_entry(self, txid: str) -> dict:
        self._guard()
        if txid not in self.mempool:
            raise RPCError(-5, "Transaction not in mempool")
        return self.mempool[txid]

    def add_mempool_tx(self, txid: str, fee: float = 0.00001) -> None:
        self.mempool[txid] = {
            "vsize": 200, "weight": 800,
            "fees": {"base": fee, "modified": fee},
            "time": 1296688602, "height": len(self.blocks),
            "ancestorcount": 1, "depends": [],
        }
