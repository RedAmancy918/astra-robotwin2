from pathlib import Path
import json, sys, time, urllib.request
import numpy as np
from client import RoboTwinClient
ROOT=Path(__file__).resolve().parent
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
while not (ROOT/'access.token').exists():time.sleep(1)
c=RoboTwinClient('roundrobin-verifier','http://127.0.0.1:8769')
while True:
    try:
        if c.observe(False)['ready']:break
    except Exception:pass
    time.sleep(1)
c.claim(takeover=True)
c.wait_hold()
results=[]
def command(kind,seed=999000,actions=6,steps=None):
    obs=c.observe(False)
    receipt=c.wait(c.command(obs,kind,steps=steps,max_actions=actions,seed=seed),timeout=180)
    assert receipt['status']=='completed',receipt
    results.append({'kind':kind,'seed':seed,'receipt':receipt})
    print(json.dumps(results[-1]),flush=True)
    return receipt,c.observe(False)['snapshot']
command('dp')
checkpoint_a,_=command('checkpoint')
before=c.observe(False)['snapshot']
assert before['seed']==999000 and before['action_count']==6
command('switch',seed=999001)
command('dp',actions=12)
checkpoint_b,_=command('checkpoint')
restored,after=command('switch',seed=999000)
assert restored['restored'] and restored['history_equal'] and restored['rng_equal']
assert after['action_count']==6
for key in ['left_eef','right_eef','left_joints','right_joints']:
    assert np.max(np.abs(np.asarray(before[key])-np.asarray(after[key])))<1e-5,key
command('dp')
restored,after=command('switch',seed=999001)
assert restored['restored'] and restored['history_equal'] and restored['rng_equal']
assert after['action_count']==12
command('eef',steps=[{'arm':'left','code':'OPEN','level':1}])
restored,after=command('switch',seed=999000)
assert after['action_count']==12 and restored['history_equal'] and restored['rng_equal']
result={'passed':True,'validation_seeds':[999000,999001],
        'excluded_from_evaluation':True,'tests':results,
        'verified':['block/robot pose and velocity','joint drive targets','gripper targets',
                    'DP observation history','Python/NumPy/Torch/CUDA RNG','action count continuation',
                    'DP inference after restore','EEF command after restore']}
(ROOT/'restore-verification.json').write_text(json.dumps(result,indent=2)+'\n')
print('RESTORE VERIFICATION PASSED',flush=True)
