"""Bitcoin Core node lifecycle management (regtest scope).

NodeManager starts a local ``bitcoind -regtest`` process against a dedicated
data directory, waits until its JSON-RPC interface is answering, verifies
the node is actually on the regtest chain (fail closed otherwise), and shuts
it down cleanly through the RPC ``stop`` command.

The manager never creates or stores credentials: authentication uses the
``.cookie`` file Bitcoin Core writes into the regtest data directory.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import time
import urllib.error
from dataclasses import dataclass
from pathlib import Path

from .rpc_client import BitcoinRPC, DEFAULT_REGTEST_PORT

logger = logging.getLogger(__name__)

STARTUP_TIMEOUT = 60.0
SHUTDOWN_TIMEOUT = 30.0


class NodeStartupError(RuntimeError):
    pass


class ChainMismatchError(RuntimeError):
    """Raised when the node under management is not on regtest."""


@dataclass
class NodeConfig:
    """Settings for a managed regtest node."""

    bitcoind: str = "bitcoind"
    datadir: str = ".bal/regtest-data"
    rpc_host: str = "127.0.0.1"
    rpc_port: int = DEFAULT_REGTEST_PORT
    # Regtest has no public peers; the milestone node is managed purely over
    # RPC, so the P2P listener is off by default (-listen=0). Flip to True
    # when P2P experiments begin.
    p2p_listen: bool = False
    extra_args: tuple = ()

    @classmethod
    def from_env(cls, env: dict | None = None) -> "NodeConfig":
        env = os.environ if env is None else env
        return cls(
            bitcoind=env.get("BAL_BITCOIND", "bitcoind"),
            datadir=env.get("BAL_DATADIR", ".bal/regtest-data"),
            rpc_host=env.get("BAL_RPC_HOST", "127.0.0.1"),
            rpc_port=int(env.get("BAL_RPC_PORT", DEFAULT_REGTEST_PORT)),
        )

    @property
    def regtest_dir(self) -> Path:
        return Path(self.datadir) / "regtest"

    @property
    def cookie_path(self) -> Path:
        return self.regtest_dir / ".cookie"

    @property
    def rpc_url(self) -> str:
        return f"http://{self.rpc_host}:{self.rpc_port}"


class NodeManager:
    """Start, verify, and stop a local regtest Bitcoin Core node."""

    def __init__(self, config: NodeConfig | None = None):
        self.config = config or NodeConfig.from_env()
        self._process: subprocess.Popen | None = None

    # --- lifecycle -------------------------------------------------------
    def start(self, timeout: float = STARTUP_TIMEOUT) -> BitcoinRPC:
        """Launch bitcoind and return a connected, regtest-verified client."""
        binary = shutil.which(self.config.bitcoind) or (
            self.config.bitcoind if Path(self.config.bitcoind).exists() else None
        )
        if binary is None:
            raise NodeStartupError(
                f"bitcoind not found: {self.config.bitcoind!r}. "
                "Install Bitcoin Core (docs/SETUP.md) or set BAL_BITCOIND."
            )
        datadir = Path(self.config.datadir)
        # Bitcoin Core 32.x refuses to start with a missing datadir.
        datadir.mkdir(parents=True, exist_ok=True)

        cmd = [
            binary, "-regtest", "-server", f"-datadir={datadir}",
            f"-rpcport={self.config.rpc_port}", "-fallbackfee=0.0002",
            "-daemonwait", *([] if self.config.p2p_listen else ["-listen=0"]),
            *self.config.extra_args,
        ]
        logger.info("starting bitcoind: %s", " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            raise NodeStartupError(
                f"bitcoind failed to start (exit {proc.returncode}): "
                f"{proc.stderr.strip() or proc.stdout.strip()}"
            )
        rpc = self.wait_for_rpc(timeout=timeout)
        self._enforce_regtest(rpc)
        logger.info("node ready: %s", self.config.rpc_url)
        return rpc

    def wait_for_rpc(self, timeout: float = STARTUP_TIMEOUT) -> BitcoinRPC:
        """Poll until the cookie exists and the RPC interface answers."""
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            if self.config.cookie_path.exists():
                try:
                    rpc = BitcoinRPC(
                        self.config.rpc_url,
                        cookie_path=str(self.config.cookie_path),
                    )
                    rpc.get_network_info()
                    return rpc
                except (urllib.error.URLError, OSError, ValueError) as exc:
                    last_error = exc
            time.sleep(0.25)
        raise NodeStartupError(
            f"RPC interface did not come up within {timeout:.0f}s"
            + (f": {last_error}" if last_error else "")
        )

    def _enforce_regtest(self, rpc: BitcoinRPC) -> None:
        chain = rpc.get_blockchain_info().get("chain")
        if chain != "regtest":
            raise ChainMismatchError(
                f"managed node reports chain={chain!r}; refusing to operate "
                "on anything but regtest"
            )

    def client(self) -> BitcoinRPC:
        """Return a client for an already-running node."""
        if not self.config.cookie_path.exists():
            raise NodeStartupError(
                f"no cookie at {self.config.cookie_path}; is the node running?"
            )
        rpc = BitcoinRPC(self.config.rpc_url,
                         cookie_path=str(self.config.cookie_path))
        self._enforce_regtest(rpc)
        return rpc

    def is_running(self) -> bool:
        try:
            self.client().uptime()
            return True
        except Exception:
            return False

    def stop(self, timeout: float = SHUTDOWN_TIMEOUT) -> None:
        """Ask the node to shut down over RPC and wait for exit."""
        try:
            self.client().stop()
        except Exception as exc:
            raise NodeStartupError(f"could not issue stop: {exc}") from exc
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not self.config.cookie_path.exists():
                logger.info("node stopped")
                return
            time.sleep(0.25)
        raise NodeStartupError(f"node did not stop within {timeout:.0f}s")

    # Context-manager sugar --------------------------------------------------
    def __enter__(self) -> BitcoinRPC:
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="Manage a local regtest Bitcoin Core node")
    ap.add_argument("action", choices=["start", "stop", "status"])
    args = ap.parse_args()

    manager = NodeManager()
    if args.action == "start":
        rpc = manager.start()
        info = rpc.get_blockchain_info()
        print(f"node running: chain={info['chain']} blocks={info['blocks']} "
              f"rpc={manager.config.rpc_url}")
    elif args.action == "stop":
        manager.stop()
        print("node stopped")
    else:
        if manager.is_running():
            info = manager.client().get_blockchain_info()
            print(f"running: chain={info['chain']} blocks={info['blocks']}")
        else:
            print("not running")


if __name__ == "__main__":
    main()
