# Contributing to Bitcoin Autonomous Lab

## Ground rules

1. **Real functionality only.** Do not implement simulated behavior and
   present it as real Bitcoin functionality. Every claimed capability needs
   a reproducible test or a live run against Bitcoin Core in `results/`.
2. **Regtest first.** All experiments run on Bitcoin Core's private regtest
   network. Code paths that could touch mainnet are gated and fail closed.
3. **No secrets in the repository.** No RPC credentials, cookies, wallets,
   or private keys. Node authentication is via the node-generated cookie
   file or environment variables (see docs/SECURITY.md).
4. **Standard library only** for application code. New third-party
   dependencies need a written justification in the pull request.

## Workflow

- Run the full test suite before pushing:
  `python3 -m unittest discover -s tests -t .`
- Live regtest integration tests (require bitcoind):
  `BAL_BITCOIND=/path/to/bitcoind python3 -m unittest tests.test_regtest_integration -v`
- Keep modules small, typed, logged, and documented.
- Every pull request describes what was executed and where the evidence lives.
