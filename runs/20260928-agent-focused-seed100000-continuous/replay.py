"""Re-execute the recorded commands in a fresh identical scene; no new model decisions."""
from pathlib import Path
import json, time, os, traceback
from client import RoboTwinClient

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'20260928-agent-focused-seed100000'

def save(name,value):
    p=ROOT/name
    tmp=p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')
    tmp.replace(p)

def progress(status,**values):
    save('progress.json',{'status':status,'updated_at':time.time(),'runner_pid':os.getpid(),
                         'mode':'recorded_agent_commands_replay','seed':100000,'dp_actions':0,**values})

def main():
    progress('waiting_for_simulator')
    start=time.monotonic()
    while True:
        try:
            c=RoboTwinClient('continuous-agent-replay','http://127.0.0.1:8772')
            obs=c.observe(False)
            if obs['ready']:break
        except Exception:
            if time.monotonic()-start>180: raise
        time.sleep(.5)
    assert obs['snapshot']['seed']==100000 and obs['snapshot']['action_count']==0
    c.claim(takeover=True);c.wait_hold()
    c.save_views(ROOT/'initial')
    executed=[]

    def perform(kind,steps=None):
        receipt=c.command(c.observe(False),kind,steps=steps,seed=100000)
        while receipt['status'] in ('queued','running'):
            time.sleep(.5)
            receipt=c.request('/v1/commands/'+receipt['command_id'])
            snap=c.observe(False)['snapshot']
            progress('replaying' if kind=='eef' else kind,command_id=receipt['command_id'],
                     completed_batches=len(executed),action_count=snap['action_count'],
                     simulation_time_s=snap['simulation_time_s'])
        return receipt

    try:
        for source_dir in sorted((SOURCE/'actions').iterdir()):
            if not (source_dir/'request.json').is_file():continue
            request=json.loads((source_dir/'request.json').read_text())
            if request['kind']!='eef':continue
            expected=json.loads((source_dir/'receipt.json').read_text())
            receipt=perform('eef',request['steps'])
            row={'source_action':source_dir.name,'request':request,'receipt':receipt,
                 'source_status':expected['status']}
            executed.append(row)
            with (ROOT/'replay-commands.jsonl').open('a') as stream:stream.write(json.dumps(row)+'\n')
            c.save_views(ROOT/'actions'/source_dir.name)
            if receipt['status']!=expected['status']:
                raise RuntimeError(f"Replay diverged at {source_dir.name}: {receipt['status']} vs {expected['status']}")
        verify=perform('verify')
        checkpoint=perform('checkpoint')
        observation=c.save_views(ROOT/'final')
        finish=perform('finish')
        assert observation['snapshot']['task_success'] and verify.get('stable_success'),'Replay did not stably succeed'
        result={'status':'complete','mode':'recorded_agent_commands_replay','success':True,
                'seed':100000,'source_run':SOURCE.name,'commands_replanned_and_executed':True,
                'same_command_sequence':True,'new_agent_inference':False,'dp_actions':0,
                'action_count':observation['snapshot']['action_count'],'batches':len(executed),
                'stability':verify,'checkpoint':checkpoint,'video':finish['video'],
                'fps':25,'sample_every_physics_steps':10,'simulation_time_s':observation['snapshot']['simulation_time_s'],
                'physics_steps':observation['snapshot']['physics_step'],'finished_at':time.time()}
        save('result.json',result);progress('complete',**{k:v for k,v in result.items() if k not in ('status','mode','seed','dp_actions')})
    except Exception as error:
        try:
            c.save_views(ROOT/'failure')
            perform('finish')
        except Exception:pass
        save('failure.json',{'error':str(error),'traceback':traceback.format_exc()})
        progress('failed',error=str(error))
        raise

if __name__=='__main__':main()
