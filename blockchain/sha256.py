"""Pure-Python SHA-256 reference, kept as a stable import path.

There is exactly one from-scratch implementation: mining.pow.sha256 (FIPS
180-4, streaming). This module re-exports its one-shot functions so older
imports keep working; the duplicate compression function that used to live
here was removed.
"""

from mining.pow.double_sha256 import double_sha256 as sha256d  # noqa: F401
from mining.pow.sha256 import sha256  # noqa: F401

__all__ = ["sha256", "sha256d"]
