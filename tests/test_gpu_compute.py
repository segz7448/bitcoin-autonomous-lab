"""GPU fault tests use doubles only to exercise failures, never as GPU evidence."""
import ctypes as ct
import hashlib
import os
import random
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from gpu.engine import (ComputeEngine, CudaBackend, CudaError,
                        MAX_BATCH, NONCE_SPACE, cpu_digest, verify_candidate)
from gpu.diagnostics.report import ATTRIBUTES, collect
from mining.pow.target import MAX_UINT256, POW_LIMIT_REGTEST, bits_to_target
from tests.pow_fixtures import GENESIS
GENESIS_HEADER = GENESIS['header']


class TestCompute(unittest.TestCase):
    def setUp(self):
        self.header = bytes(range(80))

    def test_cpu_header_matches_hashlib(self):
        result = ComputeEngine('cpu').batch(self.header, MAX_UINT256, 0, 17)
        self.assertEqual(result['hashes_computed'], 17)
        for i, h in enumerate(result['digests']):
            self.assertEqual(h, cpu_digest(self.header, i).hex())
        self.assertEqual(len(result['candidates']), 17)

    def test_genesis(self):
        h = bytes.fromhex(GENESIS_HEADER) if isinstance(GENESIS_HEADER, str) else GENESIS_HEADER
        n = int.from_bytes(h[76:80], 'little')
        out = ComputeEngine('cpu').batch(h, MAX_UINT256, n, 1)
        self.assertEqual(out['digests'][0], hashlib.sha256(hashlib.sha256(h).digest()).hexdigest())

    def test_backend_rejects_typo(self):
        with self.assertRaises(ValueError): ComputeEngine('gpu-ish')

    def test_cuda_unavailable_falls_back_auto_and_explicit(self):
        for name in ('auto', 'cuda'):
            with self.subTest(backend=name), patch('gpu.engine.CudaBackend', side_effect=CudaError('unavailable')):
                engine = ComputeEngine(name)
                result = engine.batch(self.header, 1, 0, 2)
                self.assertEqual(result['backend'], 'cpu')
                self.assertIsNotNone(result['fallback_reason'])

    def test_cuda_execution_and_allocation_failure_fallback(self):
        class Broken:
            name = 'cuda'
            def batch(self, *args): raise CudaError('allocation or launch failed')
        engine = ComputeEngine('cpu'); engine.backend = Broken()
        result = engine.batch(self.header, MAX_UINT256, 42, 4)
        self.assertEqual(result['backend'], 'cpu')
        self.assertEqual(result['digests'][0], cpu_digest(self.header, 42).hex())
        self.assertEqual(result['hashes_computed'], 4)

    def test_memoryerror_fallback(self):
        class Broken:
            name = 'cuda'
            def batch(self, *args): raise MemoryError()
        e = ComputeEngine('cpu'); e.backend = Broken()
        self.assertEqual(e.batch(self.header, 1, 0, 1)['backend'], 'cpu')

    def test_32bit_boundary_exhaustion_no_wrap(self):
        result = ComputeEngine('cpu').batch(self.header, 1, NONCE_SPACE-2, 2)
        self.assertTrue(result['exhausted']);self.assertEqual(result['hashes_computed'], 2)
        self.assertEqual(result['next_nonce'], NONCE_SPACE)
        self.assertEqual(len(result['digests']), 2)
        empty = ComputeEngine('cpu').batch(self.header, 1, NONCE_SPACE, 0)
        self.assertTrue(empty['exhausted']);self.assertEqual(empty['hashes_computed'], 0)

    def test_next_batch(self):
        e=ComputeEngine('cpu');a=e.batch(self.header,1,6,5)
        b=e.batch(self.header,1,a['next_nonce'],5)
        self.assertEqual(a['digests']+b['digests'],e.batch(self.header,1,6,10)['digests'])

    def test_invalid_arguments(self):
        cases=[dict(target=0),dict(target=-1),dict(target=True),dict(target=MAX_UINT256+1),
               dict(count=-1),dict(count=MAX_BATCH+1),dict(count=True),dict(start_nonce=True),
               dict(start_nonce=-1),dict(start_nonce=NONCE_SPACE,count=1),
               dict(threads=0),dict(threads=1025),dict(threads=True),dict(header=b'short')]
        for override in cases:
            args=dict(header=self.header,target=1,start_nonce=0,count=1,threads=128);args.update(override)
            with self.subTest(override=override),self.assertRaises(ValueError):ComputeEngine('cpu').batch(**args)

    def test_candidate_cpu_authority(self):
        d=cpu_digest(self.header,19)
        self.assertTrue(verify_candidate(self.header,MAX_UINT256,19,d))
        for nonce,digest,target in [(20,d,MAX_UINT256),(19,b'\0'*32,MAX_UINT256),(19,d,1)]:
            with self.assertRaises(CudaError):verify_candidate(self.header,target,nonce,digest)

    def test_target_equality_and_byte_order(self):
        d=cpu_digest(self.header,4);target=int.from_bytes(d,'little')
        self.assertTrue(verify_candidate(self.header,target,4,d))
        with self.assertRaises(CudaError):verify_candidate(self.header,target-1,4,d)

    def test_bits_invalid_and_limit(self):
        for bits in (0,0x20800001,0x23000001,0x2100ffff):
            header=self.header[:72]+bits.to_bytes(4,'little')+self.header[76:]
            with self.assertRaises(ValueError):ComputeEngine('cpu').batch_bits(header,POW_LIMIT_REGTEST,count=1)

    def test_bits_valid_regtest(self):
        h=self.header[:72]+(0x207fffff).to_bytes(4,'little')+self.header[76:]
        e=ComputeEngine('cpu');r=e.batch_bits(h,POW_LIMIT_REGTEST,count=32)
        for c in r['candidates']:
            self.assertTrue(verify_candidate(h,bits_to_target(0x207fffff),c['nonce'],bytes.fromhex(c['digest']),0x207fffff,POW_LIMIT_REGTEST))
        with self.assertRaises(ValueError):verify_candidate(h,MAX_UINT256,0,cpu_digest(h,0),0x207fffff)
        with self.assertRaises(ValueError):verify_candidate(h,MAX_UINT256,0,cpu_digest(h,0),0x1d00ffff)

    def test_launch_limits_fail_closed(self):
        e=object.__new__(CudaBackend)
        e.diagnostics={'limits':dict(max_threads_per_block=64,max_block_dim_x=64,max_grid_dim_x=1)}
        for count,threads in [(2,128),(65,64)]:
            with self.assertRaises(ValueError):e.batch(self.header,1,0,count,threads)
        e.diagnostics['limits']['max_grid_dim_x']=None
        with self.assertRaises(CudaError):e.batch(self.header,1,0,1,32)

    def test_corrupt_cuda_digest_and_flags_rejected(self):
        e=object.__new__(CudaBackend)
        e.diagnostics={'limits':dict(max_threads_per_block=128,max_block_dim_x=128,max_grid_dim_x=100)}
        for wrong_hash,flag in [(True,1),(False,0),(False,2)]:
            def call(header,start,count,target,threads,hashes,flags):
                digest=b'\0'*32 if wrong_hash else cpu_digest(header,start)
                ct.memmove(hashes,digest,32);ct.memmove(flags,bytes([flag]),1);return 0
            e.call=call
            with self.subTest(wrong_hash=wrong_hash,flag=flag),self.assertRaises(CudaError):e.batch(self.header,MAX_UINT256,0,1)

    def test_native_error_propagates(self):
        e=object.__new__(CudaBackend)
        e.diagnostics={'limits':dict(max_threads_per_block=128,max_block_dim_x=128,max_grid_dim_x=100)}
        for status in (2,35,700):
            e.call=lambda *args:status
            with self.assertRaises(CudaError):e.batch(self.header,1,0,1)

    def test_allowlist_only(self):
        self.assertEqual(set(ATTRIBUTES.values()),set(range(1,8)))
        r=collect(probe_kernel=False)
        self.assertEqual(set(r['limits']),set(ATTRIBUTES))
        for key in ('gpu_available','gpu_operational','driver_version','runtime_version','system_ram'):
            self.assertIn(key,r)

    def test_real_cuda_or_honest_skip(self):
        try:e=CudaBackend()
        except CudaError:self.skipTest('real CUDA unavailable; no simulated success')
        r=e.batch(self.header,MAX_UINT256,NONCE_SPACE-4,4,32)
        self.assertEqual(r[0],[cpu_digest(self.header,n) for n in range(NONCE_SPACE-4,NONCE_SPACE)])

    def test_benchmark_repeated_actual_cpu(self):
        from gpu.benchmark.run import run
        with patch('gpu.benchmark.run.CudaBackend',side_effect=CudaError('no CUDA')):
            r=run((32,64),(32,64),2)
        self.assertEqual(len(r['rows']),2)
        self.assertEqual(r['cuda_status'],'unavailable_not_benchmarked')
        self.assertIsNone(r['selected_cuda_configuration'])
        for row in r['rows']:
            self.assertEqual(len(row['elapsed_seconds']),2)
            self.assertEqual(row['total_hashes'],row['batch_size']*2)
            self.assertGreater(row['hashes_per_second'],0)

    def test_benchmark_limits(self):
        from gpu.benchmark.run import run
        for kwargs in (dict(repeats=1),dict(batch_sizes=()),dict(batch_sizes=(100000,)),dict(thread_counts=(0,))):
            with self.assertRaises(ValueError):run(**kwargs)

    def test_agent_interface(self):
        from agent.interface import AgentInterface
        a=AgentInterface()
        self.assertFalse(a.compute_benchmark_results()['ok'])
        self.assertTrue(a.compute_sha256d(self.header,'cpu')['ok'])
        self.assertFalse(a.compute_sha256d(b'x')['ok'])
        self.assertTrue(a.compute_nonce_batch(self.header,1,count=2,backend='cpu')['ok'])
        self.assertFalse(a.compute_nonce_batch(self.header,0,backend='cpu')['ok'])
        self.assertTrue(a.cuda_diagnostics()['ok'])
        self.assertTrue(a.benchmark_compute((16,),(32,),2)['ok'])
        self.assertTrue(a.compute_benchmark_results()['ok'])
        self.assertTrue(a.verify_compute_candidate(self.header,MAX_UINT256,0,cpu_digest(self.header,0))['ok'])


@unittest.skipUnless(shutil.which('g++'),'C++ compiler not available')
class TestSharedCompressionOnCPU(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory()
        root=os.path.dirname(os.path.dirname(__file__))
        output=os.path.join(cls.tmp.name,'sha.so')
        with tempfile.TemporaryFile() as log:
            p=subprocess.run(['g++','-shared','-fPIC','-O2','-Wall','-Wextra','-Werror',
                              os.path.join(root,'gpu/tests/host_sha256.cpp'),'-o',output],stdout=log,stderr=log,check=False)
        if p.returncode:raise RuntimeError('CPU-only compression test compilation failed')
        cls.lib=ct.CDLL(output)
        cls.lib.host_sha256.argtypes=[ct.c_void_p,ct.c_uint,ct.c_void_p]
        cls.lib.host_sha256d.argtypes=[ct.c_void_p,ct.c_uint32,ct.c_void_p]
        cls.lib.host_meets.argtypes=[ct.c_void_p,ct.c_void_p];cls.lib.host_meets.restype=ct.c_bool

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_sha256_padding_vectors(self):
        rng=random.Random(4004)
        for n in (0,1,3,31,32,55,56,63,64,65,79,80,127,128,129,1000):
            data=bytes(rng.randrange(256) for _ in range(n));out=ct.create_string_buffer(32)
            self.lib.host_sha256(data,n,out)
            self.assertEqual(out.raw,hashlib.sha256(data).digest())

    def test_sha256d_80byte_randomized(self):
        rng=random.Random(444)
        for _ in range(100):
            h=bytes(rng.randrange(256) for _ in range(80));n=rng.randrange(1<<32);out=ct.create_string_buffer(32)
            self.lib.host_sha256d(h,n,out);self.assertEqual(out.raw,cpu_digest(h,n))

    def test_little_endian_target_predicate(self):
        for n in (0,1,255,256,1<<255,MAX_UINT256):
            for t in (0,1,255,256,1<<255,MAX_UINT256):
                self.assertEqual(self.lib.host_meets(n.to_bytes(32,'little'),t.to_bytes(32,'little')),n<=t)
