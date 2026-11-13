"""Independent observer for a second fresh Regtest run. No repository edits.
Wrappers call the original functions unchanged, recording only public block work.
No RPC authentication, wallet keys or credential-bearing objects are recorded.
"""
import hashlib
import json
import runpy
import sys
from pathlib import Path

repo = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo))
import mining.engine.session as session
import mining.engine.search as search
from gpu.engine import ComputeEngine
from node.rpc_client import BitcoinRPC

root = Path(__file__).resolve().parent
evidence = {'built': [], 'batches': [], 'cpu_verifications': [], 'rpc_methods': [], 'submissions': []}
build = session.build_candidate
validate = search.validate_header
batch = ComputeEngine.batch
call = BitcoinRPC.call

def observe_build(*args, **kwargs):
    candidate = build(*args, **kwargs)
    evidence['built'].append({'height': candidate.height, 'builder': 'mining.engine.builder.build_candidate'})
    return candidate

def observe_validate(*args, **kwargs):
    result = validate(*args, **kwargs)
    evidence['cpu_verifications'].append(result.as_dict())
    return result

def observe_batch(self, *args, **kwargs):
    result = batch(self, *args, **kwargs)
    evidence['batches'].append({k: result[k] for k in ('backend', 'hashes_computed', 'requested_backend')})
    return result

def observe_call(self, method, *params, **kwargs):
    evidence['rpc_methods'].append(method)
    result = call(self, method, *params, **kwargs)
    if method == 'submitblock':
        raw = bytes.fromhex(params[0])
        digest = hashlib.sha256(hashlib.sha256(raw[:80]).digest()).digest()[::-1].hex()
        evidence['submissions'].append({'block_hash': digest, 'bytes': len(raw), 'block_hex': params[0], 'submitblock_result': result})
    return result

session.build_candidate = observe_build
search.validate_header = observe_validate
ComputeEngine.batch = observe_batch
BitcoinRPC.call = observe_call
sys.argv = [str(repo / 'scripts/milestone_005_006.py'), '--cycles', '3']
try:
    runpy.run_path(sys.argv[0], run_name='__main__')
except SystemExit as exc:
    evidence['milestone_exit_code'] = exc.code
finally:
    (root / 'observed-run.json').write_text(json.dumps(evidence, indent=2) + '\n')
checks = {
    'milestone_exit_zero': evidence.get('milestone_exit_code') == 0,
    'own_builder_three_candidates': len(evidence['built']) == 3,
    'cpu_verified_three_solutions': len(evidence['cpu_verifications']) == 3 and all(x['valid'] for x in evidence['cpu_verifications']),
    'three_full_block_submissions': len(evidence['submissions']) == 3 and all(x['bytes'] > 80 and x['submitblock_result'] is None for x in evidence['submissions']),
    'matching_cpu_and_submitted_hashes': [x['hash'] for x in evidence['cpu_verifications']] == [x['block_hash'] for x in evidence['submissions']],
    'no_generation_rpc': not any(x.startswith('generate') for x in evidence['rpc_methods']),
    'real_cpu_hash_batches': bool(evidence['batches']) and all(x['backend'] == 'cpu' and x['hashes_computed'] > 0 for x in evidence['batches']),
}
print('\nINDEPENDENT OBSERVER CHECKS')
for name, ok in checks.items():
    print(f'{name}: {ok}')
print('RPC methods used:', ', '.join(sorted(set(evidence['rpc_methods']))))
print('Full blocks and function/RPC evidence: observed-run.json')
if not all(checks.values()):
    raise SystemExit(1)
