# mining/

Proof-of-work research modules. Contents:

- `miner.py` - CPU nonce scanner (double SHA-256 over 80-byte headers) plus
  an independent `verify_pow` check.
- `block.py` - BIP34-exact coinbase construction (with optional BIP141
  witness commitment) and block assembly.
- `template_miner.py` - end-to-end regtest flow: getblocktemplate, build,
  mine, submitblock, confirm acceptance. Fails closed on template shapes it
  does not handle and refuses any chain other than regtest.

Scope: these modules are exercised on Bitcoin Core's private regtest network
only. TASK 001's milestone uses Core's own `generatetoaddress` for block
production; PoW template mining is research code for later milestones, not
part of the milestone acceptance criteria. No mainnet mining.
