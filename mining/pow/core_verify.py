"""Compare this engine's results with a live Bitcoin Core node (regtest).

Everything here uses real RPC replies; nothing is faked. Each check
computes a value with the independent engine and compares it with what
Core reports.
"""

from __future__ import annotations


from .block_header import BlockHeader
from .difficulty import block_work, difficulty_from_bits
from .nonce_search import NonceSearcher
from .target import POW_LIMITS, bits_to_target
from .validator import validate_header

HEADER_HEX_LEN = 160


def verify_block(rpc, block_hash: str, pow_limit: int) -> dict:
    """Verify one block header against Core. Returns per-check booleans."""
    meta = rpc.call("getblockheader", block_hash, True)
    raw_hex = rpc.call("getblockheader", block_hash, False)     # Core's own 80 bytes
    full_hex = rpc.call("getblock", block_hash, 0)               # serialized block
    header = BlockHeader.from_rpc(meta)
    parsed = BlockHeader.from_hex(raw_hex)
    pow_result = validate_header(header, pow_limit)
    checks = {
        "serialization_matches_core_hex": header.hex() == raw_hex,
        "deserialization_roundtrip": parsed.serialize().hex() == raw_hex and parsed == header,
        "header_is_prefix_of_block": full_hex[:HEADER_HEX_LEN] == raw_hex,
        "hash_matches_core": header.hash_display() == meta["hash"] == block_hash,
        "fast_hash_matches": header.hash_fast() == header.hash(),
        "bits_match": f"{header.bits:08x}" == meta["bits"],
        "target_matches_core": f"{bits_to_target(header.bits):064x}" == meta["target"],
        "difficulty_matches_core": abs(difficulty_from_bits(header.bits) - meta["difficulty"])
                                   <= 1e-12 * max(1.0, meta["difficulty"]),
        "chainwork_step_consistent": True,
        "pow_valid": pow_result.valid,
    }
    if "previousblockhash" in meta:
        prev = rpc.call("getblockheader", meta["previousblockhash"], True)
        checks["prev_hash_links"] = header.prev_hash_display == prev["hash"] == meta["previousblockhash"]
        checks["chainwork_step_consistent"] = (
            int(meta["chainwork"], 16) - int(prev["chainwork"], 16) == block_work(header.bits))
    return {"height": meta["height"], "hash": meta["hash"], "nonce": header.nonce,
            "bits": meta["bits"], "checks": checks, "all_ok": all(checks.values()),
            "pow_hash_int_hex": f"{pow_result.hash_int:064x}",
            "target_hex": f"{pow_result.target:064x}"}


def verify_chain(rpc, pow_limit: int | None = None) -> dict:
    """Verify every block 0..tip on the node's active chain."""
    info = rpc.call("getblockchaininfo")
    limit = pow_limit if pow_limit is not None else POW_LIMITS.get(
        {"regtest": "regtest", "main": "main"}.get(info["chain"], ""), None)
    if limit is None:
        raise ValueError(f"no pow limit known for chain {info['chain']!r}")
    rows = [verify_block(rpc, rpc.call("getblockhash", h), limit)
            for h in range(info["blocks"] + 1)]
    return {"chain": info["chain"], "tip_height": info["blocks"], "blocks": rows,
            "all_ok": all(r["all_ok"] for r in rows)}


def tamper_to_invalid_pow(block_hex: str, pow_limit: int) -> tuple[str, dict]:
    """Return (block_hex with a nonce that fails PoW per OUR validator, our verdict)."""
    raw = bytearray(bytes.fromhex(block_hex))
    header = BlockHeader.deserialize(bytes(raw[:80]))
    for nonce in range(header.nonce + 1, header.nonce + 100000):
        cand = header.with_nonce(nonce % (1 << 32))
        verdict = validate_header(cand, pow_limit)
        if not verdict.valid:
            raw[:80] = cand.serialize()
            return raw.hex(), verdict.as_dict()
    raise RuntimeError("could not find an invalid nonce (target too easy)")


def mine_block_with_engine(rpc, payout_script: bytes, pow_limit: int) -> dict:
    """getblocktemplate -> own nonce search -> submitblock; Core must accept it.

    Reuses the lab's coinbase/block assembly (mining.block / template_miner)
    and replaces only the hashing/search with this engine.
    """
    from mining.block import assemble_block
    from mining.template_miner import build_block_from_template, require_regtest

    require_regtest(rpc.call("getblockchaininfo")["chain"])
    template = rpc.get_block_template()
    old_header, txs, _ = build_block_from_template(template, payout_script)
    candidate = old_header.serialize()
    searcher = NonceSearcher()
    result = searcher.search_bits(candidate, pow_limit, max_seconds=60)
    if not result.found:
        raise RuntimeError(f"engine did not find a nonce: {result.status.value}")
    solved = BlockHeader.deserialize(candidate).with_nonce(result.nonce)
    old_header.nonce = result.nonce
    block_hex = assemble_block(old_header, txs).hex()
    if block_hex[:HEADER_HEX_LEN] != solved.hex():
        raise RuntimeError("assembled block does not start with the solved header")
    reject = rpc.submit_block(block_hex)
    height = template["height"]
    core_hash = rpc.get_block_hash(height) if reject is None else None
    return {"height": height, "nonce": result.nonce, "hashes_attempted": result.hashes_attempted,
            "elapsed_s": round(result.elapsed, 6), "engine_hash": solved.hash_display(),
            "submitblock_result": reject, "core_hash_at_height": core_hash,
            "accepted_and_matches": reject is None and core_hash == solved.hash_display()}
