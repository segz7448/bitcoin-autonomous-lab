"""Text dashboard: render node/chain state for humans and logs.

Pure rendering functions plus a small CLI (python -m dashboard.status) that
prints a live snapshot from the running regtest node.
"""

from __future__ import annotations

from blockchain.monitor import BlockVerification, NodeStatus
from node.node_manager import NodeManager


def render_status(status: NodeStatus) -> str:
    lines = [
        "Bitcoin Autonomous Lab - node status",
        "-" * 46,
        f"  chain                 {status.chain}",
        f"  blocks / headers      {status.blocks} / {status.headers}",
        f"  best block            {status.best_block_hash}",
        f"  difficulty            {status.difficulty:g}",
        f"  verification progress {status.verification_progress:.6f}",
        f"  mempool transactions  {status.mempool_size}",
        f"  peer connections      {status.connections}",
        f"  node uptime           {status.node_uptime_s}s",
    ]
    return "\n".join(lines)


def render_verification(report: BlockVerification) -> str:
    def mark(flag: bool) -> str:
        return "PASS" if flag else "FAIL"

    return "\n".join([
        f"block {report.block_hash}",
        f"  height {report.height} | {report.n_tx} tx | "
        f"{report.confirmations} confirmation(s)",
        f"  [{mark(report.hash_recomputed)}] block hash recomputed locally",
        f"  [{mark(report.pow_meets_target)}] proof-of-work meets target",
        f"  [{mark(report.recognized_by_node)}] recognized by node (getblock)",
        f"  [{mark(report.prev_link_ok)}] previous-block linkage",
    ])


def main() -> None:
    manager = NodeManager()
    from blockchain.monitor import ChainMonitor

    monitor = ChainMonitor(manager.client())
    print(render_status(monitor.snapshot()))
    print()
    print(render_verification(monitor.verify_tip()))


if __name__ == "__main__":
    main()
