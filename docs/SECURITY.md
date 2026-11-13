# Security

## Credentials

- **Nothing secret is in this repository.** No RPC usernames, passwords,
  cookies, wallet files, or private keys are committed; `.gitignore` excludes
  the `.bal/` data directories where Bitcoin Core writes them.
- **Cookie authentication is the default.** Bitcoin Core generates a random
  `.cookie` file per datadir at startup with owner-only permissions. The lab
  reads it at runtime and never copies it anywhere.
- **Explicit credentials only via environment.** If cookie auth is not
  available, `BAL_RPC_USER`/`BAL_RPC_PASSWORD` are read from the environment
  - never from source code, never from a committed file.
- **Regtest wallets only.** Milestone code creates a throwaway regtest
  wallet (`bal`) solely so `generatetoaddress` has a payout address. It
  holds valueless test coins and is deleted with the temporary datadir.

## Network exposure

The managed node binds its RPC interface to `127.0.0.1` only, on regtest,
with no inbound peer connections expected (regtest has no public peers).
Do not point this software at a mainnet, testnet, or signet datadir: the
chain guard (`ChainMismatchError`, `require_regtest`) will refuse, and that
refusal is a safety feature, not a limitation to work around.

## Verification posture

The lab recomputes block hashes and proof-of-work targets from RPC reply
fields rather than trusting them. Bugs or tampering that make the node
report inconsistent chain data surface as failed verifications.
