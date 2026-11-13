"""End-to-end regtest mining against a local Bitcoin Core node.

Fetches a real block template with getblocktemplate, builds the coinbase and
merkle root, scans nonces with the CPU miner, submits the assembled block
with submitblock, and confirms the node accepted it onto its chain. The
reference implementation validates the block under real consensus rules.

Scope handled:
  - empty templates (coinbase only), no witness commitment needed
  - templates whose transactions carry witness data: a BIP141 witness
    commitment is computed and embedded, and cross-checked against the
    template's default_witness_commitment when Core provides one
Anything else fails closed with an explicit error rather than a silent
wrong submission. Regtest only: the chain check refuses every other network.
"""

from __future__ import annotations

import argparse
import logging
import time

from blockchain.primitives import (
    BlockHeader, display_to_internal, internal_to_display, merkle_root,
    sha256d_fast,
)
from node.rpc_client import BitcoinRPC

from .block import assemble_block, build_coinbase_tx
from .miner import mine_header

logger = logging.getLogger(__name__)

# The BIP141 witness reserved value. Zero is the standard choice.
RESERVED_VALUE = b"\x00" * 32


def require_regtest(chain: str) -> None:
    """Refuse to mine on any chain but regtest."""
    if chain != "regtest":
        raise RuntimeError(f"refusing to mine on chain {chain!r}; regtest only")


def build_block_from_template(template: dict, payout_script: bytes) -> tuple[BlockHeader, list[bytes], int]:
    """Build (header, txs, witness_tx_count) from a getblocktemplate reply."""
    template_txs = template.get("transactions", [])
    for tx in template_txs:
        for field in ("txid", "data"):
            if field not in tx:
                raise RuntimeError(
                    f"template transaction missing {field!r}; refusing to guess"
                )

    txids = [display_to_internal(tx["txid"]) for tx in template_txs]
    # getblocktemplate's "hash" is the witness txid (wtxid); for a non-witness
    # transaction it equals the txid. Missing means treat as non-witness.
    wtxids = [
        display_to_internal(tx.get("hash") or tx["txid"]) for tx in template_txs
    ]
    witness_count = sum(
        1 for tx, w in zip(template_txs, wtxids)
        if w != display_to_internal(tx["txid"])
    )

    commitment = None
    if witness_count:
        witness_root = merkle_root([b"\x00" * 32] + wtxids)  # coinbase slot = 0
        commitment = sha256d_fast(witness_root + RESERVED_VALUE)
        expected = template.get("default_witness_commitment")
        if expected and commitment.hex() not in expected:
            raise RuntimeError(
                "computed witness commitment disagrees with Core's "
                "default_witness_commitment; refusing to submit"
            )

    coinbase = build_coinbase_tx(
        height=template["height"],
        value_sats=template["coinbasevalue"],
        script_pubkey=payout_script,
        coinbase_flags=template.get("coinbaseaux", {}).get("flags", ""),
        witness_commitment=commitment,
    )
    all_txids = [coinbase.txid_internal] + txids
    header = BlockHeader(
        version=template["version"],
        prev_hash_display=template["previousblockhash"],
        merkle_root_display=internal_to_display(merkle_root(all_txids)),
        timestamp=max(template["curtime"], template["mintime"]),
        bits=int(template["bits"], 16),
        nonce=0,
    )
    txs = [coinbase.full] + [bytes.fromhex(tx["data"]) for tx in template_txs]
    return header, txs, witness_count


def mine_one_block(rpc, payout_script: bytes,
                   max_seconds: float = 60.0, verbose: bool = True) -> dict:
    """Mine and submit one block. Returns a result dict with evidence."""
    template = rpc.get_block_template()
    header, txs, witness_count = build_block_from_template(template, payout_script)

    started = time.monotonic()
    result = mine_header(header, max_seconds=max_seconds)
    if not result.found:
        raise RuntimeError(
            f"no winning nonce in {result.hashes} hashes "
            f"({result.seconds:.1f}s) -- unexpected on regtest difficulty"
        )
    header.nonce = result.nonce

    block_hex = assemble_block(header, txs).hex()
    block_hash = header.hash_display()
    reject_reason = rpc.submit_block(block_hex)

    evidence = {
        "height": template["height"],
        "block_hash": block_hash,
        "nonce": result.nonce,
        "hashes_tried": result.hashes,
        "seconds": round(result.seconds, 4),
        "hashrate_hs": round(result.hashrate, 1),
        "template_transactions": len(template.get("transactions", [])),
        "witness_transactions": witness_count,
        "submitblock_reject_reason": reject_reason,
        "accepted": reject_reason is None,
    }
    if verbose:
        for k, v in evidence.items():
            print(f"  {k}: {v}")

    if reject_reason is not None:
        raise RuntimeError(f"block rejected by node: {reject_reason}")

    # Confirm the node committed the block to its active chain.
    committed = rpc.get_block(block_hash)
    evidence["confirmations"] = committed["confirmations"]
    if committed["confirmations"] < 1:
        raise RuntimeError("block not on the active chain after submission")
    evidence["seconds_total"] = round(time.monotonic() - started, 4)
    return evidence


def main() -> None:
    ap = argparse.ArgumentParser(description="Mine regtest blocks against a local node")
    ap.add_argument("--rpc-url", default="http://127.0.0.1:18443")
    ap.add_argument("--cookie", required=True, help="path to .cookie file")
    ap.add_argument("--blocks", type=int, default=1)
    args = ap.parse_args()

    rpc = BitcoinRPC(args.rpc_url, cookie_path=args.cookie)
    info = rpc.get_blockchain_info()
    require_regtest(info["chain"])
    print(f"connected: chain={info['chain']} height={info['blocks']}")

    address = rpc.get_new_address()
    script = bytes.fromhex(rpc.get_address_info(address)["scriptPubKey"])
    print(f"payout address: {address}")

    for i in range(args.blocks):
        print(f"mining block {i + 1}/{args.blocks} ...")
        mine_one_block(rpc, script)


if __name__ == "__main__":
    main()
