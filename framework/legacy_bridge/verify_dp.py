import time,json
from pathlib import Path
from client import RoboTwinClient
c=RoboTwinClient('dp-verification');watcher=RoboTwinClient('ai-takeover')
report={}
c.claim(True);obs=c.wait_hold()
# Use the actual first trained checkpoint and execute a full two-action smoke run.
r=c.command(obs,'dp',max_actions=2)
result=c.wait(r,timeout=180)
report['rollout']=result
assert result['status']=='completed' and result['actions_executed']==2,result
assert result['checkpoint'].endswith('.ckpt')
obs=c.observe(False)
reset=c.wait(c.command(obs,'reset',seed=1000));assert reset['status']=='completed',reset
obs=c.observe(False)
r=c.command(obs,'dp',max_actions=120)
time.sleep(.25)
before=watcher.observe(False)
t=time.monotonic();watcher.claim(True);held=watcher.wait_hold(timeout=60)
result=watcher.wait(r)
assert result['status']=='cancelled',result
report['dp_takeover']={'applied_after_s':time.monotonic()-t,'frame_id_while_dp':before['snapshot']['frame_id'],'frame_age_while_dp_s':before['frame_age_s'],'receipt':result}
# Allow already-running inference to drain before resetting the simulator.
time.sleep(3)
obs=watcher.observe(False)
result=watcher.wait(watcher.command(obs,'reset',seed=1000))
assert result['status']=='completed',result
report['reset']=result
watcher.save_views(Path(__file__).parent/'verification/dp-final')
(Path(__file__).parent/'verification/dp-results.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
