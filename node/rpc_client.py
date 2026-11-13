"""Bitcoin Core JSON-RPC client (Python standard library only).

Authentication follows Bitcoin Core's own defaults: the per-datadir
``.cookie`` file the node generates on startup. Explicit user/password is
supported for nodes configured with ``rpcuser``/``rpcpassword``. No
credential is ever hardcoded; see docs/SECURITY.md.

Error model:
  * RPCError - the node answered with a JSON-RPC error payload.
  * urllib.error.URLError - the node is unreachable (connection refused,
    timeout, DNS). Callers that manage node lifecycle treat URLError as
    "node not up".
"""

from __future__ import annotations

import base64
import json
import logging
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_REGTEST_PORT = 18443
DEFAULT_TIMEOUT = 120.0


class RPCError(Exception):
    """The node returned a JSON-RPC error payload."""

    def __init__(self, code: int, message: str):
        super().__init__(f"RPC error {code}: {message}")
        self.code = code
        self.message = message


@dataclass
class RPCConfig:
    """Connection settings for one Bitcoin Core RPC endpoint."""

    host: str = "127.0.0.1"
    port: int = DEFAULT_REGTEST_PORT
    cookie_path: str | None = None
    user: str | None = None
    password: str | None = None
    timeout: float = DEFAULT_TIMEOUT

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @classmethod
    def from_env(cls, env: dict | None = None) -> "RPCConfig":
        """Build a config from BAL_RPC_* environment variables.

        BAL_RPC_HOST, BAL_RPC_PORT, BAL_RPC_COOKIE, BAL_RPC_USER,
        BAL_RPC_PASSWORD, BAL_RPC_TIMEOUT. Unset values fall back to the
        regtest defaults above.
        """
        env = os.environ if env is None else env
        return cls(
            host=env.get("BAL_RPC_HOST", "127.0.0.1"),
            port=int(env.get("BAL_RPC_PORT", DEFAULT_REGTEST_PORT)),
            cookie_path=env.get("BAL_RPC_COOKIE") or None,
            user=env.get("BAL_RPC_USER") or None,
            password=env.get("BAL_RPC_PASSWORD") or None,
            timeout=float(env.get("BAL_RPC_TIMEOUT", DEFAULT_TIMEOUT)),
        )

    def validate(self) -> None:
        if not (1 <= self.port <= 65535):
            raise ValueError(f"invalid RPC port: {self.port}")
        if self.cookie_path is None and (self.user is None) != (self.password is None):
            raise ValueError("user and password must be set together")


class BitcoinRPC:
    """Minimal JSON-RPC client for a Bitcoin Core node."""

    def __init__(self, url: str, cookie_path: str | None = None,
                 user: str | None = None, password: str | None = None,
                 timeout: float = DEFAULT_TIMEOUT):
        self.url = url
        self.timeout = timeout
        if cookie_path:
            creds = Path(cookie_path).read_text().strip()
            token = base64.b64encode(creds.encode()).decode()
        elif user is not None and password is not None:
            token = base64.b64encode(f"{user}:{password}".encode()).decode()
        else:
            raise ValueError("cookie_path or user/password required")
        self._auth = f"Basic {token}"
        self._id = 0

    @classmethod
    def from_config(cls, config: RPCConfig) -> "BitcoinRPC":
        config.validate()
        return cls(config.url, cookie_path=config.cookie_path,
                   user=config.user, password=config.password,
                   timeout=config.timeout)

    def call(self, method: str, *params):
        self._id += 1
        body = json.dumps({
            "jsonrpc": "1.0", "id": self._id, "method": method,
            "params": list(params),
        }).encode()
        req = urllib.request.Request(
            self.url, data=body,
            headers={"Authorization": self._auth,
                     "Content-Type": "application/json"},
        )
        logger.debug("rpc %s(%s)", method,
                     ", ".join(json.dumps(p)[:80] for p in params))
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                reply = json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            # Core answers RPC-level errors with HTTP 4xx/5xx plus a JSON
            # error body; surface the JSON-RPC error, not the HTTP status.
            try:
                reply = json.loads(exc.read())
            except Exception:
                raise exc
            if reply.get("error"):
                raise RPCError(reply["error"]["code"],
                               reply["error"]["message"]) from exc
            raise
        if reply.get("error"):
            raise RPCError(reply["error"]["code"], reply["error"]["message"])
        return reply["result"]

    # --- Blockchain queries -------------------------------------------------
    def get_blockchain_info(self) -> dict:
        return self.call("getblockchaininfo")

    def get_block_count(self) -> int:
        return self.call("getblockcount")

    def get_block_hash(self, height: int) -> str:
        return self.call("getblockhash", height)

    def get_block(self, block_hash: str, verbosity: int = 1) -> dict:
        return self.call("getblock", block_hash, verbosity)

    def get_best_block_hash(self) -> str:
        return self.call("getbestblockhash")

    # --- Node / network -------------------------------------------------------
    def get_network_info(self) -> dict:
        return self.call("getnetworkinfo")

    def get_mempool_info(self) -> dict:
        return self.call("getmempoolinfo")

    def uptime(self) -> int:
        return self.call("uptime")

    def stop(self) -> str:
        return self.call("stop")

    # --- Wallets and block generation (regtest scope) --------------------------
    def create_wallet(self, name: str = "bal") -> dict:
        return self.call("createwallet", name)

    def list_wallets(self) -> list:
        return self.call("listwallets")

    def get_new_address(self) -> str:
        return self.call("getnewaddress")

    def get_address_info(self, address: str) -> dict:
        return self.call("getaddressinfo", address)

    def generate_to_address(self, nblocks: int, address: str,
                            maxtries: int = 1_000_000) -> list:
        """Regtest-only RPC: mine nblocks to address using Core's miner."""
        return self.call("generatetoaddress", nblocks, address, maxtries)

    # --- Mining ----------------------------------------------------------
    def get_block_template(self, rules=None) -> dict:
        return self.call("getblocktemplate",
                         {"rules": rules or ["segwit"], "capabilities": []})

    def submit_block(self, block_hex: str):
        return self.call("submitblock", block_hex)

    # --- Headers / chain tips (TASK 002) ------------------------------------
    def get_block_header(self, block_hash: str) -> dict:
        return self.call("getblockheader", block_hash)

    def get_chain_tips(self) -> list:
        return self.call("getchaintips")

    # --- Transactions / mempool (TASK 002) ------------------------------------
    def get_raw_transaction(self, txid: str, verbose: bool = True) -> dict:
        return self.call("getrawtransaction", txid, verbose)

    def decode_raw_transaction(self, tx_hex: str) -> dict:
        return self.call("decoderawtransaction", tx_hex)

    def get_raw_mempool(self, verbose: bool = False):
        return self.call("getrawmempool", verbose)

    def get_mempool_entry(self, txid: str) -> dict:
        return self.call("getmempoolentry", txid)

    def send_to_address(self, address: str, amount: float) -> str:
        """Regtest wallet spend used by tests and the milestone demo."""
        return self.call("sendtoaddress", address, amount)

    # --- Chain manipulation (regtest test support) ------------------------------
    def invalidate_block(self, block_hash: str) -> None:
        """Regtest-only RPC: mark a block invalid, forcing a reorg."""
        self.call("invalidateblock", block_hash)

    def reconsider_block(self, block_hash: str) -> None:
        self.call("reconsiderblock", block_hash)
