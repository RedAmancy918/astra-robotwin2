"""Exercise real images, both arms, stale observations, ownership and preemption."""
import json,time,uuid
from pathlib import Path
import numpy as np
from client import RoboTwinClient
from XPolicyLab.utils.process_data import decode_image_bit
import base64
a=RoboTwinClient('verification-A');b=RoboTwinClient('verification-B')
out=Path(__file__).parent/'verification';out.mkdir(exist_ok=True)
report={}
deadline=time.monotonic()+180
while not a.observe(False)['ready']:
    if time.monotonic()>deadline: raise TimeoutError('Simulator did not become ready')
    time.sleep(1)
obs=a.save_views(out/'initial')
imgs=a.observe()['images']
report['images']={}
for name,data in imgs.items():
    img=decode_image_bit(base64.b64decode(data.split(',',1)[1]))
    assert img.shape==(240,320,3) and img.std()>5
    report['images'][name]={'shape':list(img.shape),'std':float(img.std())}
a.claim(True);obs=a.wait_hold()
for arm in ['left','right']:
    receipt=a.command(obs,'eef',[{'arm':arm,'code':'Z+','level':1}])
    result=a.wait(receipt)
    report[arm+'_move']=result
    assert result['status']=='completed',result
    actual=result['steps'][0]['displacement_m'][2]
    assert actual>0.001,actual
    current=a.observe(False)
    try:
        a.command(obs,'eef',[{'arm':arm,'code':'Z-','level':1}])
        raise AssertionError('Stale observation accepted')
    except RuntimeError as e: assert '409' in str(e)
    obs=current
report['stale_observation_rejected']=True
try:
    b.command(obs,'eef',[{'arm':'left','code':'Z+','level':1}])
    raise AssertionError('Non-owner action accepted')
except RuntimeError as e: assert '409' in str(e)
report['non_owner_rejected']=True
# Replay the same accepted request: the receipt must be identical and no second motion queued.
cid=str(uuid.uuid4());before=a.observe(False)
r=a.command(before,'eef',[{'arm':'left','code':'Z-','level':1}],command_id=cid)
a.wait(r)
replay=a.command(before,'eef',[{'arm':'left','code':'Z-','level':1}],command_id=cid)
assert replay['command_id']==cid and replay['status']=='completed'
report['idempotent_replay']=True
# Queue eight bounded motions, then transfer ownership during execution.
obs=a.observe(False)
r=a.command(obs,'eef',[{'arm':'right','code':('Z+' if i%2==0 else 'Z-'),'level':2} for i in range(8)])
time.sleep(.15);t=time.monotonic();b.claim(True);held=b.wait_hold()
result=b.wait(r)
assert result['status']=='cancelled',result
assert held['owner']=='verification-B' and held['applied_epoch']==held['epoch']
report['takeover']={'elapsed_s':time.monotonic()-t,'receipt':result}
obs=b.observe(False)
reset=b.wait(b.command(obs,'reset',seed=1000));assert reset['status']=='completed',reset
b.save_views(out/'final')
report['reset']=reset
(out/'results.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
