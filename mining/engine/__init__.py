"""TASK 005 autonomous Bitcoin mining engine.

Stages (each independently tested, regtest only):

- ``template``  - mining-work acquisition: getblocktemplate retrieval,
  strict validation and staleness detection (Phase 2).
- ``builder``   - candidate block construction from a template (Phase 3).
- ``search``    - Proof-of-Work nonce search with exhaustion/extranonce
  handling (Phase 4).
- ``session``   - submit/verify loop with persistent statistics
  (Phases 5-6).

Nothing here replaces the existing components; the engine reuses
``mining.block``, ``mining.template_miner``, ``mining.pow`` and the node
RPC client through their public interfaces.
"""
