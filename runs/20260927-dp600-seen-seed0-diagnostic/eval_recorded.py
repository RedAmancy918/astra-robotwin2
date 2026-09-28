"""Instrument the upstream single-environment evaluator without changing its decisions."""
from pathlib import Path
import os,sys,json,time,hashlib,traceback,math,subprocess
ROOT=Path('/mnt/data/yjh/RoboTwin')
PROJECT=Path('/mnt/data/yjh/astra-vla')
RUN=Path(os.environ['ASTRA_VLA_RUN'])
PORT=int(os.environ['ASTRA_VLA_POLICY_PORT'])
TARGET=int(os.environ.get('ASTRA_VLA_TEST_NUM','20'))
SEED_INDEX=int(os.environ.get('ASTRA_VLA_SEED_INDEX','0'))
os.chdir(ROOT)
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import eval_policy_xpolicylab as official
import numpy as np

start=time.monotonic()
records=[]
attempts=set()
expert_records=[]
runtime={'env':None,'started':None,'completed_actions':0,'error':None}

def write_json(path,data):
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))
    temp.replace(path)

def progress(status='running'):
    counted=[r for r in records if r['counted']]
    successes=sum(r['success'] for r in counted)
    result={'status':status,'completed':len(counted),'planned':TARGET,'successes':successes,
        'success_rate':successes/len(counted) if counted else None,'elapsed_s':time.monotonic()-start,
        'last_episode':records[-1] if records else None,'seed_attempts':len(attempts)}
    write_json(RUN/'progress.json',result)
    return result

original_factory=official.class_decorator
def factory(name):
    env=original_factory(name)
    runtime['env']=env
    orig_setup,orig_expert,orig_action=env.setup_demo,env.play_once,env.take_action
    def setup(**kwargs):
        seed=int(kwargs['seed']);attempts.add(seed)
        runtime['seed']=seed
        if len(attempts)>100: raise SystemExit('More than 100 candidate seeds; aborting evaluation')
        try: return orig_setup(**kwargs)
        except Exception as exc:
            with (RUN/'setup-errors.jsonl').open('a') as f:
                f.write(json.dumps({'seed':seed,'error':repr(exc)})+'\n')
            raise
    def expert():
        try:
            result=orig_expert()
            rec={'seed':runtime['seed'],'plan_success':bool(env.plan_success),'success':bool(env.check_success())}
            return result
        except Exception as exc:
            rec={'seed':runtime['seed'],'success':False,'error':repr(exc)}
            raise
        finally:
            expert_records.append(rec)
            with (RUN/'expert-checks.jsonl').open('a') as f: f.write(json.dumps(rec)+'\n')
    def action(*args,**kwargs):
        try: result=orig_action(*args,**kwargs)
        except Exception as exc:
            runtime['error']={'type':'environment_error','message':repr(exc)}
            raise
        runtime['completed_actions']+=1
        return result
    env.setup_demo,env.play_once,env.take_action=setup,expert,action
    return env
official.class_decorator=factory

original_client=official.build_policy_client
def client(args):
    c=original_client(args)
    call=c.call
    def recorded_call(*args,**kwargs):
        try: return call(*args,**kwargs)
        except Exception as exc:
            if kwargs.get('func_name') in ['update_obs','get_action']:
                runtime['error']={'type':'policy_error','message':repr(exc)}
            raise
    c.call=recorded_call
    return c
official.build_policy_client=client

orig_prepare,orig_end=official.prepare_policy_case,official.notify_trial_end
def prepare(c,task,seed,instruction,action_type):
    runtime.update(started=time.monotonic(),completed_actions=0,error=None)
    return orig_prepare(c,task,seed,instruction,action_type)
def ended(c,task,seed,success):
    result=orig_end(c,task,seed,success)
    env=runtime['env'];steps=runtime['completed_actions']
    counted=bool(success or steps>0)
    reason='success' if success else ('step_limit' if env.take_action_cnt>=env.step_lim else 'rollout_error')
    if not counted: reason='error_before_first_action_excluded_by_upstream'
    rec={'episode_index':sum(r['counted'] for r in records),'seed':int(seed),'success':bool(success),
        'counted':counted,'reason':reason,'actions':steps,'step_limit':int(env.step_lim),
        'wall_time_s':time.monotonic()-runtime['started'],'error':runtime['error'],
        'video':str(RUN/'videos'/f'episode{env.test_num}.mp4')}
    records.append(rec)
    with (RUN/'episodes.jsonl').open('a') as f: f.write(json.dumps(rec,allow_nan=False)+'\n')
    p=progress()
    print('ASTRA_VLA_EPISODE '+json.dumps(p,ensure_ascii=False),flush=True)
    return result
official.prepare_policy_case,official.notify_trial_end=prepare,ended
official.build_eval_save_dir=lambda *args,**kwargs: RUN/'videos'

args={'task_name':'stack_blocks_two','task_config':'demo_clean','policy_name':'DP',
      'ckpt_name':'yjh_dp50_clean-stack_blocks_two-aloha_agilex-joint-0',
      'ckpt_setting':'600','bench_name':'RoboTwin','env_cfg_type':'aloha_agilex',
      'host':'127.0.0.1','port':PORT,'protocol':'ws','seed':SEED_INDEX,'test_num':TARGET,
      'eval_batch':False,'expert_check':True,'action_type':'joint','frequency':30,
      'xpolicylab_root':str(ROOT/'XPolicyLab'),'evaluation_id':RUN.name,
      'trial_id':'dp600-clean20','action_case_id':'stack_blocks_two'}
write_json(RUN/'evaluation-arguments.json',args)
progress()
try:
    official.main(args)
    result=progress('complete')
    assert result['completed']==TARGET, result
    n=result['completed'];p=result['success_rate'];z=1.959963984540054
    mid=(p+z*z/(2*n))/(1+z*z/n)
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    result.update(wilson_95_percent=[100*(mid-half),100*(mid+half)],checkpoint_epoch=600,
        protocol=f'RoboTwin demo_clean, expert-solvable seeds starting at {100000*(1+SEED_INDEX)}, 800 actions',
        evaluated_seeds=[r['seed'] for r in records if r['counted']],
        expert_rejected_seeds=[r['seed'] for r in expert_records if not r['success']])
    write_json(RUN/'summary.json',result)
    import csv
    with (RUN/'episodes.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(records[0]));writer.writeheader();writer.writerows(records)
    print('ASTRA_VLA_FINAL '+json.dumps(result,ensure_ascii=False),flush=True)
except BaseException as exc:
    result=progress('failed');result['error']=repr(exc)
    write_json(RUN/'failure.json',result)
    raise
