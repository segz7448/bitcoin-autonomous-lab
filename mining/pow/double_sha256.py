"""Bitcoin's double SHA-256: SHA256(SHA256(data)).

Two implementations are exposed on purpose:
  double_sha256       - this package's own SHA-256 (independent reference)
  double_sha256_fast  - hashlib/OpenSSL, used in the nonce-search hot loop
Tests assert both agree on every vector and on real blocks.
"""

from __future__ import annotations

import hashlib

from .sha256 import sha256


def double_sha256(data) -> bytes:
    return sha256(sha256(data))


def double_sha256_hex(data) -> str:
    return double_sha256(data).hex()


def double_sha256_fast(data) -> bytes:
    return hashlib.sha256(hashlib.sha256(bytes(data)).digest()).digest()
