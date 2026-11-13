# The regtest environment

Regtest is Bitcoin Core's private regression-test network: real consensus
rules, no peers, instant low-difficulty block production, and coins that are
worthless by design. Every experiment in this repository runs there.

Properties used by this project:

- `generatetoaddress` mines blocks on demand (regtest-only RPC). It is a
  Bitcoin Core testing utility, used here only by the early milestones
  (001/002) and by tests that need to advance the tip independently. It
  is NOT the project's mining path: the autonomous mining engine
  (`mining/engine/`, milestone 005/006) obtains work with
  `getblocktemplate`, constructs candidate blocks itself, searches the
  SHA256d nonce space itself, and submits with `submitblock`.
- Block subsidy on a fresh regtest chain is 50 BTC per block; rewards need
  100 confirmations to mature (the same coinbase maturity rule as mainnet).
  Nothing on regtest has economic value.
- Default RPC port is 18443; the node writes a `.cookie` credential file
  into `<datadir>/regtest/` at startup.
- The regtest genesis block differs from mainnet's; chain params are
  `chain=regtest` in `getblockchaininfo`. The lab checks this on every
  connection and refuses to operate on any other chain.

Typical session:

```bash
./scripts/regtest_up.sh
python3 -c "
from node.node_manager import NodeManager
from blockchain.monitor import ChainMonitor
rpc = NodeManager().client()
print(ChainMonitor(rpc).generate_and_verify(1, rpc.get_new_address()))
"
./scripts/regtest_down.sh
```
