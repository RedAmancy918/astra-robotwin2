from pathlib import Path
import sys,json,time,urllib.request
r=Path(__file__).resolve().parent
sys.path.insert(0,str(r));urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
from client import RoboTwinClient
c=RoboTwinClient('dp600-controller',base_url='http://127.0.0.1:8767')
remaining=650
records=[]
try:
    while remaining>0:
        obs=c.observe(False)
        if obs['snapshot']['task_success']: break
        result=c.wait(c.command(obs,'dp',max_actions=min(120,remaining)),timeout=60)
        records.append(result)
        with (r/'recovery-rollout.jsonl').open('a') as f: f.write(json.dumps(result)+'\n')
        assert result['status']=='completed',result
        count=result['actions_executed'];remaining-=count
        after=c.observe(False)
        progress={'status':'running','remaining_dp_actions':remaining,'additional_dp_actions':650-remaining,'task_success':after['snapshot']['task_success'],'total_action_count':after['snapshot']['action_count']}
        (r/'recovery-progress.json').write_text(json.dumps(progress,indent=2)+'\n')
        print(json.dumps(progress),flush=True)
        if after['snapshot']['task_success']: break
        assert count>0, 'Policy made no progress'
    final=c.observe(False)
    progress={'status':'complete','remaining_dp_actions':remaining,'additional_dp_actions':650-remaining,'task_success':final['snapshot']['task_success'],'total_action_count':final['snapshot']['action_count']}
    (r/'recovery-progress.json').write_text(json.dumps(progress,indent=2)+'\n')
    (r/'recovery-final-observation.json').write_text(json.dumps(final,indent=2)+'\n')
    print(json.dumps(progress),flush=True)
except BaseException as exc:
    (r/'recovery-error.json').write_text(json.dumps({'error':repr(exc),'records':records},indent=2)+'\n')
    raise
