"""Bounded batch SHA256d with CPU authority and fail-closed CUDA fallback."""
from __future__ import annotations
import ctypes as ct
import hashlib
import time
from pathlib import Path
from mining.pow.target import MAX_UINT256, bits_to_target
from gpu.diagnostics.report import collect

MAX_BATCH = 1 << 20  # bounded output/verification memory; 32 MiB digests
NONCE_SPACE = 1 << 32


class CudaError(RuntimeError):
    pass


def uint(name, value, low, high):
    if not isinstance(value, int) or isinstance(value, bool) or not low <= value <= high:
        raise ValueError(f'{name} must be an integer in [{low}, {high}]')
    return value


def validate(header, target, start, count, threads=128):
    if not isinstance(header, bytes) or len(header) != 80:
        raise ValueError('header must be exactly 80 bytes')
    uint('target', target, 1, MAX_UINT256)
    uint('start_nonce', start, 0, NONCE_SPACE)
    uint('count', count, 0, MAX_BATCH)
    uint('threads', threads, 1, 1024)
    if start + count > NONCE_SPACE:
        raise ValueError('nonce batch crosses the 32-bit boundary')


def cpu_digest(header, nonce):
    h = header[:76] + nonce.to_bytes(4, 'little')
    return hashlib.sha256(hashlib.sha256(h).digest()).digest()


def verify_candidate(header, target, nonce, digest, bits=None, pow_limit=MAX_UINT256):
    """Explicit target is a computational threshold; bits adds consensus checks."""
    uint('nonce', nonce, 0, NONCE_SPACE - 1)
    uint('pow_limit', pow_limit, 1, MAX_UINT256)
    validate(header, target, nonce, 1)
    if bits is not None:
        if bits != int.from_bytes(header[72:76], 'little'):
            raise ValueError('nBits disagrees with original header')
        decoded = bits_to_target(bits)
        if decoded != target or decoded > pow_limit:
            raise ValueError('target disagrees with valid nBits/pow limit')
    if not isinstance(digest, bytes) or len(digest) != 32:
        raise ValueError('candidate digest must be exactly 32 bytes')
    if cpu_digest(header, nonce) != digest:
        raise CudaError('candidate failed independent CPU hash verification')
    if int.from_bytes(digest, 'little') > target:
        raise CudaError('candidate does not meet target')
    return True


class CpuBackend:
    name = 'cpu'

    def batch(self, header, target, start, count, threads=128):
        validate(header, target, start, count, threads)
        hashes = [cpu_digest(header, nonce) for nonce in range(start, start + count)]
        flags = [int.from_bytes(digest, 'little') <= target for digest in hashes]
        return hashes, flags


class CudaBackend:
    name = 'cuda'

    def __init__(self, diagnostics=None):
        self.diagnostics = diagnostics if diagnostics is not None else collect(probe_kernel=False)
        if not self.diagnostics['cuda_accessible']:
            raise CudaError('CUDA unavailable: driver/runtime/device access required')
        try:
            self.lib = ct.CDLL(str(Path(__file__).parent / 'cuda' / 'libbal_cuda.so'))
            self.call = self.lib.bal_batch
            self.call.argtypes = [ct.c_void_p, ct.c_uint64, ct.c_uint32, ct.c_void_p,
                                  ct.c_uint, ct.c_void_p, ct.c_void_p]
            self.call.restype = ct.c_int
        except (OSError, AttributeError):
            raise CudaError('CUDA computation library not built or incompatible') from None
        # Nontrivial header, multiple nonces, independently checked before selection.
        hashes, flags = self.batch(bytes(range(80)), MAX_UINT256, 0x10203040, 3, 32)
        if len(hashes) != 3 or not all(flags):
            raise CudaError('CUDA self-test failed')

    def batch(self, header, target, start, count, threads=128):
        validate(header, target, start, count, threads)
        if count == 0:
            return [], []
        limits = self.diagnostics['limits']
        max_threads = limits.get('max_threads_per_block')
        max_x = limits.get('max_block_dim_x')
        max_grid = limits.get('max_grid_dim_x')
        if any(v is None for v in (max_threads, max_x, max_grid)):
            raise CudaError('CUDA launch limits unavailable')
        if threads > min(max_threads, max_x) or (count + threads - 1) // threads > max_grid:
            raise ValueError('launch exceeds approved CUDA limits')
        hashes = ct.create_string_buffer(count * 32)
        flags = ct.create_string_buffer(count)
        dispatch_start = time.perf_counter()
        status = self.call(header, start, count, target.to_bytes(32, 'little'), threads, hashes, flags)
        self.last_device_batch_seconds = time.perf_counter() - dispatch_start
        if status:
            raise CudaError(f'CUDA batch failed with status {status}')
        result = [hashes.raw[i*32:(i+1)*32] for i in range(count)]
        matches = []
        # Verify EVERY returned digest and flag, not only advertised winners.
        # A corrupt kernel cannot silently hide candidates or claim bad hashes.
        for i, digest in enumerate(result):
            if digest != cpu_digest(header, start+i):
                raise CudaError('CUDA digest failed independent CPU verification')
            match = int.from_bytes(digest, 'little') <= target
            if flags.raw[i] not in (0, 1) or bool(flags.raw[i]) != match:
                raise CudaError('CUDA target predicate failed independent CPU verification')
            matches.append(match)
        return result, matches


class ComputeEngine:
    def __init__(self, backend='auto'):
        if backend not in ('auto', 'cpu', 'cuda'):
            raise ValueError('backend must be auto, cpu or cuda')
        self.requested_backend = backend
        self.fallback_reason = None
        self.backend = CpuBackend()
        if backend != 'cpu':
            try:
                self.backend = CudaBackend()
            except (CudaError, OSError, ValueError):
                self.fallback_reason = 'CUDA unavailable or self-test failed'

    def batch(self, header, target, start_nonce=0, count=4096, threads=128):
        validate(header, target, start_nonce, count, threads)
        begin = time.perf_counter()
        fallback_in_batch = False
        try:
            hashes, matches = self.backend.batch(header, target, start_nonce, count, threads)
        except (CudaError, OSError, MemoryError):
            self.backend = CpuBackend()
            self.fallback_reason = 'CUDA execution failed; recomputed full batch on CPU'
            fallback_in_batch = True
            hashes, matches = self.backend.batch(header, target, start_nonce, count, threads)
        candidates = []
        for i, match in enumerate(matches):
            if match:
                nonce = start_nonce + i
                verify_candidate(header, target, nonce, hashes[i])
                candidates.append({'nonce': nonce, 'digest': hashes[i].hex()})
        return dict(backend=self.backend.name, requested_backend=self.requested_backend,
                    fallback_reason=self.fallback_reason,
                    fallback_in_batch=fallback_in_batch, hashes_computed=count,
                    next_nonce=start_nonce+count, exhausted=start_nonce+count == NONCE_SPACE,
                    elapsed_seconds=time.perf_counter()-begin,
                    digests=[d.hex() for d in hashes], candidates=candidates)

    def batch_bits(self, header, pow_limit, **kwargs):
        if not isinstance(header, bytes) or len(header) != 80:
            raise ValueError('header must be exactly 80 bytes')
        uint('pow_limit', pow_limit, 1, MAX_UINT256)
        target = bits_to_target(int.from_bytes(header[72:76], 'little'))
        if target > pow_limit:
            raise ValueError('nBits target exceeds pow limit')
        return self.batch(header, target, **kwargs)
