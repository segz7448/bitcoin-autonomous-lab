"""Actual Core regtest data through unified computation, no public network."""
import os
import shutil
import tempfile
import unittest
from gpu.engine import ComputeEngine, CudaBackend, CudaError, verify_candidate
from mining.pow.block_header import BlockHeader
from mining.pow.target import POW_LIMIT_REGTEST, bits_to_target
from node.node_manager import NodeConfig, NodeManager
BITCOIND=os.environ.get('BAL_BITCOIND') or shutil.which('bitcoind')


@unittest.skipUnless(BITCOIND,'Core unavailable')
class TestComputeCore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.manager=NodeManager(NodeConfig(bitcoind=BITCOIND,datadir=cls.temp.name,rpc_port=18449))
        cls.rpc=cls.manager.start()
        cls.rpc.create_wallet('compute')
        cls.rpc.generate_to_address(4,cls.rpc.get_new_address())

    @classmethod
    def tearDownClass(cls):
        cls.manager.stop();cls.temp.cleanup()

    def test_core_headers_cpu_and_auto(self):
        for height in range(5):
            h=self.rpc.get_block_hash(height)
            raw=BlockHeader.from_rpc(self.rpc.get_block_header(h)).serialize()
            nonce=int.from_bytes(raw[76:80],'little');target=bits_to_target(int.from_bytes(raw[72:76],'little'))
            for backend in ('cpu','auto'):
                r=ComputeEngine(backend).batch_bits(raw,POW_LIMIT_REGTEST,start_nonce=nonce,count=1)
                self.assertEqual(bytes.fromhex(r['digests'][0])[::-1].hex(),h)
                self.assertEqual(len(r['candidates']),1)
                self.assertTrue(verify_candidate(raw,target,nonce,bytes.fromhex(r['digests'][0]),
                                                int.from_bytes(raw[72:76],'little'),POW_LIMIT_REGTEST))

    def test_core_header_real_cuda_or_skip(self):
        try:e=CudaBackend()
        except CudaError:self.skipTest('CUDA execution blocked; Core CPU validation runs separately')
        h=self.rpc.get_best_block_hash();raw=BlockHeader.from_rpc(self.rpc.get_block_header(h)).serialize()
        n=int.from_bytes(raw[76:80],'little');t=bits_to_target(int.from_bytes(raw[72:76],'little'))
        hashes,flags=e.batch(raw,t,n,1,32)
        self.assertEqual(hashes[0][::-1].hex(),h);self.assertTrue(flags[0])
