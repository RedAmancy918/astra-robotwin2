"""Check EEF-only enforcement and scene restoration on excluded seeds."""
from pathlib import Path
import json
import time
import urllib.request
import numpy as np
from client import RoboTwinClient
from agent_runtime import validate_decision

ROOT = Path(__file__).resolve().parent
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
deadline = time.monotonic() + 180
while not (ROOT/'access.token').exists():
    assert time.monotonic() < deadline, 'Server startup timed out'
    time.sleep(1)
c = RoboTwinClient('agent-only-verifier', 'http://127.0.0.1:8770')
while True:
    try:
        if c.observe(False)['ready']:
            break
    except Exception:
        pass
    assert time.monotonic() < deadline, 'Server readiness timed out'
    time.sleep(1)
c.claim(takeover=True)
c.wait_hold()
start = c.observe(False)
assert start['snapshot']['policy_mode'] == 'agent_only'
assert start['snapshot']['dp_enabled'] is False
assert start['snapshot']['action_count'] == 0
try:
    c.command(start, 'dp', max_actions=6)
except RuntimeError as exc:
    assert str(exc).startswith('422:'), str(exc)
else:
    raise AssertionError('Server accepted a DP request')
after_rejection = c.observe(False)
assert after_rejection['revision'] == start['revision']
assert after_rejection['snapshot']['action_count'] == 0
try:
    validate_decision({'kind': 'dp', 'dp_actions': 6, 'steps': [],
                       'visual_assessment': '', 'reason': '', 'memory': ''})
except Exception:
    pass
else:
    raise AssertionError('Agent schema accepted a DP decision')
results = []


def command(kind, seed=999010, steps=None):
    receipt = c.wait(c.command(c.observe(False), kind, steps=steps, seed=seed), timeout=120)
    assert receipt['status'] == 'completed', receipt
    results.append({'kind': kind, 'seed': seed, 'receipt': receipt})
    print(json.dumps({'kind': kind, 'seed': seed, 'status': receipt['status'],
                     'restored': receipt.get('restored'),
                     'physical_error': receipt.get('physical_max_abs_error')}), flush=True)
    return receipt, c.observe(False)['snapshot']


command('eef', steps=[{'arm': 'left', 'code': 'CLOSE', 'level': 1}])
_, before = command('checkpoint')
assert before['seed'] == 999010 and before['action_count'] == 1
command('switch', seed=999011)
command('eef', seed=999011, steps=[{'arm': 'right', 'code': 'CLOSE', 'level': 1},
                                   {'arm': 'left', 'code': 'OPEN', 'level': 1}])
command('checkpoint', seed=999011)
restored, after = command('switch', seed=999010)
assert restored['restored'] and restored['history_equal'] and restored['rng_equal']
assert after['action_count'] == 1
for key in ['left_eef', 'right_eef', 'left_joints', 'right_joints',
            'left_gripper_target', 'right_gripper_target']:
    assert np.max(np.abs(np.asarray(before[key])-np.asarray(after[key]))) < 1e-5, key
command('eef', steps=[{'arm': 'left', 'code': 'OPEN', 'level': 1}])
restored, after = command('switch', seed=999011)
assert after['action_count'] == 2 and restored['rng_equal']
restored, after = command('switch', seed=999010)
assert after['action_count'] == 2 and restored['rng_equal']
command('finish')
result = {'passed': True, 'validation_seeds': [999010, 999011],
          'excluded_from_evaluation': True, 'dp_request_rejected': True,
          'dp_rejection_mutated_scene': False, 'agent_schema_rejects_dp': True,
          'tests': results,
          'verified': ['EEF execution from home pose', 'restorable physical state',
                       'joint and gripper drive targets', 'action counters',
                       'Python/NumPy/Torch/CUDA RNG', 'EEF continuation after restore'],
          'limitations': ['derived acceleration cache and contact solver warm-start cache are not bitwise restored']}
(ROOT/'restore-verification.json').write_text(json.dumps(result, indent=2)+'\n')
print('AGENT-ONLY RESTORE VERIFICATION PASSED', flush=True)
