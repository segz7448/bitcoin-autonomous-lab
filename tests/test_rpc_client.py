"""RPC client behavior: config, auth, error mapping - no live node needed."""

import base64
import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from node.rpc_client import BitcoinRPC, RPCConfig, RPCError  # noqa: E402


class _RecordingHandler(BaseHTTPRequestHandler):
    """Captures the request, replies with a canned JSON-RPC result."""

    captured = {}

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        _RecordingHandler.captured = {
            "authorization": self.headers.get("Authorization"),
            "content_type": self.headers.get("Content-Type"),
            "payload": json.loads(body),
        }
        reply = json.dumps({
            "jsonrpc": "1.0", "id": _RecordingHandler.captured["payload"]["id"],
            "result": {"chain": "regtest", "blocks": 0}, "error": None,
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *args):
        pass


class _ServerFixture(unittest.TestCase):
    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), _RecordingHandler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()


class TestRPCConfig(unittest.TestCase):
    def test_defaults_are_regtest(self):
        cfg = RPCConfig()
        self.assertEqual(cfg.port, 18443)
        self.assertEqual(cfg.url, "http://127.0.0.1:18443")

    def test_from_env_overrides(self):
        cfg = RPCConfig.from_env({
            "BAL_RPC_HOST": "10.0.0.9", "BAL_RPC_PORT": "18555",
            "BAL_RPC_USER": "u", "BAL_RPC_PASSWORD": "p",
        })
        self.assertEqual((cfg.host, cfg.port, cfg.user, cfg.password),
                         ("10.0.0.9", 18555, "u", "p"))

    def test_validate_rejects_bad_port(self):
        with self.assertRaises(ValueError):
            RPCConfig(port=70000).validate()

    def test_validate_rejects_half_credentials(self):
        with self.assertRaises(ValueError):
            RPCConfig(user="u").validate()

    def test_no_hardcoded_credentials(self):
        # A config built from an empty environment carries no credential.
        cfg = RPCConfig.from_env({})
        self.assertIsNone(cfg.user)
        self.assertIsNone(cfg.password)
        self.assertIsNone(cfg.cookie_path)


class TestRPCClientAuth(_ServerFixture):
    def test_cookie_auth_header(self, ):
        cookie = self._write_cookie("__cookie__:s3cret-cookie-value")
        rpc = BitcoinRPC(f"http://127.0.0.1:{self.port}", cookie_path=cookie)
        result = rpc.get_blockchain_info()
        self.assertEqual(result["chain"], "regtest")
        expected = base64.b64encode(b"__cookie__:s3cret-cookie-value").decode()
        self.assertEqual(_RecordingHandler.captured["authorization"],
                         f"Basic {expected}")
        self.assertEqual(_RecordingHandler.captured["content_type"],
                         "application/json")
        self.assertEqual(_RecordingHandler.captured["payload"]["method"],
                         "getblockchaininfo")

    def test_user_password_auth_header(self):
        rpc = BitcoinRPC(f"http://127.0.0.1:{self.port}",
                         user="alice", password="wonder")
        rpc.call("getblockcount")
        expected = base64.b64encode(b"alice:wonder").decode()
        self.assertEqual(_RecordingHandler.captured["authorization"],
                         f"Basic {expected}")

    def _write_cookie(self, contents: str) -> str:
        import tempfile
        fd, path = tempfile.mkstemp(prefix="bal-cookie-")
        with os.fdopen(fd, "w") as fh:
            fh.write(contents)
        self.addCleanup(os.unlink, path)
        return path


class TestRPCErrorMapping(unittest.TestCase):
    def test_error_payload_raises_with_code(self):
        # Covered exhaustively in test_adversarial.TestRPCFailures; here we
        # only pin the message formatting contract.
        err = RPCError(-28, "Loading wallet...")
        self.assertEqual(err.code, -28)
        self.assertIn("-28", str(err))
        self.assertIn("Loading wallet", str(err))


if __name__ == "__main__":
    unittest.main()
