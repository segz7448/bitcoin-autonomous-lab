"""SHA-256 per FIPS 180-4, written from the specification.

Supports arbitrary-length byte input (one-shot or streaming), binary and
hexadecimal output. The performance path of the engine uses hashlib
(OpenSSL); this module is the independent reference that the tests
cross-check against hashlib and the NIST/FIPS vectors.
"""

from __future__ import annotations

import struct

_MASK = 0xFFFFFFFF

_K = (
    0x428A2F98, 0x71374491, 0xB5C0FBCF, 0xE9B5DBA5, 0x3956C25B, 0x59F111F1,
    0x923F82A4, 0xAB1C5ED5, 0xD807AA98, 0x12835B01, 0x243185BE, 0x550C7DC3,
    0x72BE5D74, 0x80DEB1FE, 0x9BDC06A7, 0xC19BF174, 0xE49B69C1, 0xEFBE4786,
    0x0FC19DC6, 0x240CA1CC, 0x2DE92C6F, 0x4A7484AA, 0x5CB0A9DC, 0x76F988DA,
    0x983E5152, 0xA831C66D, 0xB00327C8, 0xBF597FC7, 0xC6E00BF3, 0xD5A79147,
    0x06CA6351, 0x14292967, 0x27B70A85, 0x2E1B2138, 0x4D2C6DFC, 0x53380D13,
    0x650A7354, 0x766A0ABB, 0x81C2C92E, 0x92722C85, 0xA2BFE8A1, 0xA81A664B,
    0xC24B8B70, 0xC76C51A3, 0xD192E819, 0xD6990624, 0xF40E3585, 0x106AA070,
    0x19A4C116, 0x1E376C08, 0x2748774C, 0x34B0BCB5, 0x391C0CB3, 0x4ED8AA4A,
    0x5B9CCA4F, 0x682E6FF3, 0x748F82EE, 0x78A5636F, 0x84C87814, 0x8CC70208,
    0x90BEFFFA, 0xA4506CEB, 0xBEF9A3F7, 0xC67178F2,
)

_H0 = (
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
)


def _rotr(x: int, n: int) -> int:
    return ((x >> n) | (x << (32 - n))) & _MASK


def _compress(state: list, block: bytes) -> None:
    w = list(struct.unpack(">16I", block))
    for t in range(16, 64):
        s0 = _rotr(w[t - 15], 7) ^ _rotr(w[t - 15], 18) ^ (w[t - 15] >> 3)
        s1 = _rotr(w[t - 2], 17) ^ _rotr(w[t - 2], 19) ^ (w[t - 2] >> 10)
        w.append((w[t - 16] + s0 + w[t - 7] + s1) & _MASK)
    a, b, c, d, e, f, g, h = state
    for t in range(64):
        s1 = _rotr(e, 6) ^ _rotr(e, 11) ^ _rotr(e, 25)
        ch = (e & f) ^ (~e & _MASK & g)
        t1 = (h + s1 + ch + _K[t] + w[t]) & _MASK
        s0 = _rotr(a, 2) ^ _rotr(a, 13) ^ _rotr(a, 22)
        maj = (a & b) ^ (a & c) ^ (b & c)
        t2 = (s0 + maj) & _MASK
        h, g, f, e, d, c, b, a = g, f, e, (d + t1) & _MASK, c, b, a, (t1 + t2) & _MASK
    for i, v in enumerate((a, b, c, d, e, f, g, h)):
        state[i] = (state[i] + v) & _MASK


def _as_bytes(data) -> bytes:
    if isinstance(data, (bytes, bytearray, memoryview)):
        return bytes(data)
    raise TypeError(f"SHA-256 input must be bytes-like, got {type(data).__name__}")


class SHA256:
    """Streaming SHA-256 (update / digest / hexdigest / copy)."""

    digest_size = 32
    block_size = 64

    def __init__(self, data: bytes = b""):
        self._state = list(_H0)
        self._buf = b""
        self._length = 0  # total message length in bytes
        if data:
            self.update(data)

    def update(self, data) -> "SHA256":
        data = _as_bytes(data)
        self._length += len(data)
        buf = self._buf + data
        full = len(buf) - (len(buf) % 64)
        for off in range(0, full, 64):
            _compress(self._state, buf[off:off + 64])
        self._buf = buf[full:]
        return self

    def copy(self) -> "SHA256":
        other = SHA256()
        other._state = list(self._state)
        other._buf = self._buf
        other._length = self._length
        return other

    def digest(self) -> bytes:
        state = list(self._state)
        bit_len = self._length * 8
        tail = self._buf + b"\x80"
        tail += b"\x00" * ((56 - len(tail)) % 64)
        tail += struct.pack(">Q", bit_len)
        for off in range(0, len(tail), 64):
            _compress(state, tail[off:off + 64])
        return struct.pack(">8I", *state)

    def hexdigest(self) -> str:
        return self.digest().hex()


def sha256(data) -> bytes:
    """SHA-256 digest (32 bytes) of a bytes-like object."""
    return SHA256(_as_bytes(data)).digest()


def sha256_hex(data) -> str:
    """SHA-256 digest as lowercase hex."""
    return sha256(data).hex()
