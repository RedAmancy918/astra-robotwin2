"""One visual decision per unfinished scene per round, no episode budget."""
from pathlib import Path
import fcntl, json, os, time, traceback
import agent_runtime as a
from client import RoboTwinClient

ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'20260927-dp600-agent-unlimited-clean20'
SEEDS=list(range(100000,100020))
ORDER=SEEDS[1:]+SEEDS[:1]  # Give the untouched scenes their first turns first.
STATES={}
ROUND=0
CLIENTS={}

def persist():
    a.save(ROOT/'states'/f"{a.CURRENT['seed']}.json",a.CURRENT)

def progress(phase,**extra):
    # Keep every scene visible, including those not yet visited or still pending.
    if a.CURRENT.get('seed') in STATES:
        STATES[a.CURRENT['seed']]=a.CURRENT
    rows=[]
    for seed in SEEDS:
        state=STATES[seed]
        rows.append({'seed':seed,'status':state.get('episode_status','not_started'),
                     'visits':state.get('visits',0),'action_count':state.get('action_count',0),
                     'agent_decisions':state.get('decision_index',0),
                     'success':state.get('result',{}).get('success'),
                     'error':state.get('last_error')})
    completed=sum(x['success'] is not None for x in rows)
    successes=sum(x['success'] is True for x in rows)
    failures=sum(x['success'] is False for x in rows)
    value={'status':phase,'updated_at':time.time(),'runner_pid':os.getpid(),
           'round':ROUND,'planned':20,'started':sum(x['visits']>0 or x['action_count']>0 for x in rows),
           'completed':completed,'successes':successes,'failures':failures,'pending':20-completed,
           'current_seed':a.CURRENT.get('seed'),'action_count':a.CURRENT.get('action_count',0),
           'agent_decisions':a.CURRENT.get('decision_index',0),
           'episode_step_limit':None,'episode_time_limit_s':None,
           'decisions_per_visit':1,'scenes':rows,**extra}
    a.save(ROOT/'progress.json',value)
    report=['# DP600 + 视觉 agent：20 局轮转评估','',
            f"状态：{phase}；轮次 {ROUND}；已有 {value['started']}/20 局获得执行机会。",
            f"成功 {successes}；失败 {failures}；未完成 {20-completed}。",'',
            '每局每轮执行一次视觉 agent 决策，之后轮到下一局；整局没有时间、动作或决策次数上限。',
            '初次进入新场景先执行 120 个 DP 动作，再进行该轮的一次视觉决策。',
            '未完成场景保存进度后继续，不会因轮转被重置或计为失败。',
            '首局从旧串行任务的 178 个动作、7 次已执行决策继续，仿真进程保持原状。',
            '其余场景保存物理状态、驱动目标、夹爪状态、策略观测历史和随机数状态；每次恢复验证一致性。',
            '不保证恢复后物理接触求解器的内部缓存或渲染噪声逐位一致；这是轮转协议的限制。',
            'Seed 100000–100019；demo_clean；600.ckpt；gpt-6-astra / max；三视角 RGB 和机器人状态。',
            '结束条件仍为官方成功或方块掉至地面；基础设施异常保留为未完成。',
            '视频按场景分段录制并保留动作计数；首局视频仍在旧 run。', '',
            '| seed | 状态 | 轮转访问 | 总动作 | agent 决策 |', '|---|---|---:|---:|---:|']
    for row in rows:
        report.append(f"| {row['seed']} | {row['status']} | {row['visits']} | {row['action_count']} | {row['agent_decisions']} |")
    report+=['','未完成场景存在时只报告成功/失败/未完成数量，不把部分完成的比例当作最终成功率。']
    if completed==20:report+=['',f'最终成功率：{successes}/20 = {successes/20:.1%}。']
    (ROOT/'REPORT.md').write_text('\n'.join(report)+'\n')

a.persist=persist
a.progress=progress

def select(seed):
    a.CURRENT=STATES[seed]
    a.CLIENT=CLIENTS[0 if seed==100000 else 1]
    obs=a.fresh()
    if obs['owner']!=a.CLIENT.client_id:
        a.CLIENT.claim(takeover=True)
        a.CLIENT.wait_hold()
    obs=a.fresh()
    if seed==100000:
        assert obs['snapshot']['seed']==100000,'Preserved first episode changed unexpectedly'
    elif obs['snapshot']['seed']!=seed:
        if a.CURRENT.get('pending_command') and a.CURRENT['pending_command']['kind']!='switch':
            raise RuntimeError('Unresolved action receipt; do not restore/reset this scene')
        progress('restoring_scene')
        a.perform('switch',seed=seed)
    obs=a.fresh()
    assert obs['snapshot']['seed']==seed
    return obs

def finish_if_terminal():
    snap=a.fresh()['snapshot']
    if not(snap['task_success'] or snap['terminal_failure']):return False
    receipt=a.perform('finish')
    item={'seed':a.CURRENT['seed'],'success':snap['task_success'],
          'reason':'official_success' if snap['task_success'] else snap['terminal_failure']['reason'],
          'action_count':snap['action_count'],'agent_decisions':a.CURRENT['decision_index'],
          'visits':a.CURRENT['visits'],'round':ROUND,'step_limit':None,'time_limit_s':None,
          'wall_time_s':time.time()-a.CURRENT['started_at'],'final_video':receipt['video']}
    a.CURRENT['result']=item
    a.CURRENT['episode_status']='success' if item['success'] else 'failure'
    persist()
    a.save(ROOT/'episodes'/str(a.CURRENT['seed'])/'result.json',item)
    a.append(ROOT/'episodes.jsonl',item)
    return True

def visit(seed):
    select(seed)
    state=a.CURRENT
    state['visits']=state.get('visits',0)+1
    state['episode_status']='in_progress'
    state.pop('last_error',None)
    persist()
    if finish_if_terminal():return
    if not state.get('warmup_done'):
        progress('initial_dp_rollout')
        receipt=a.perform('dp',actions=120)
        state['history'].append({'kind':'dp','reason':'Initial DP observation interval','receipt':receipt})
        state['warmup_done']=True
        persist()
        if finish_if_terminal():return
    if state.get('pending_decision') is None:
        decision,views=a.infer()
        state['pending_decision']={'decision':decision,'views':views}
        persist()
    pending=state['pending_decision']
    decision=pending['decision']
    receipt=a.perform(decision['kind'],decision['steps'],decision['dp_actions'])
    state['history'].append({'decision':decision,'receipt':receipt})
    state['history']=state['history'][-12:]
    state['memory']=decision['memory']
    state['previous_views']=pending['views']
    state['decision_index']+=1
    state['pending_decision']=None
    persist()
    a.append(ROOT/'decisions.jsonl',{'time':time.time(),'seed':seed,'round':ROUND,
             'index':state['decision_index'],'decision':decision,'receipt':receipt})
    if finish_if_terminal():return
    if seed!=100000:
        a.perform('checkpoint',seed=seed)
    state['episode_status']='pending_next_round'
    persist()
    a.append(ROOT/'visits.jsonl',{'time':time.time(),'round':ROUND,'seed':seed,
             'action_count':state['action_count'],'agent_decisions':state['decision_index']})
    progress('yielding_to_next_scene')

def main():
    global ROUND,STATES,CLIENTS
    lock=(ROOT/'driver.lock').open('w')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    assert json.loads((ROOT/'restore-verification.json').read_text())['passed']
    (ROOT/'states').mkdir(exist_ok=True)
    (ROOT/'agent-workspace').mkdir(exist_ok=True)
    for seed in SEEDS:
        p=ROOT/'states'/f'{seed}.json'
        (ROOT/'episodes'/str(seed)).mkdir(parents=True,exist_ok=True)
        if p.exists():
            state=json.loads(p.read_text())
        elif seed==100000:
            state=json.loads((OLD/'driver-state.json').read_text())
            assert state['seed']==seed and not state.get('pending_command') and not state.get('pending_decision')
            state['episode_status']='preserved_from_serial'
            state['visits']=0
        else:
            state={'seed':seed,'started_at':time.time(),'decision_index':0,'inference_attempt':0,
                   'history':[],'memory':'','action_count':0,'warmup_done':False,
                   'visits':0,'episode_status':'not_started'}
        STATES[seed]=state
        a.save(p,state)
    CLIENTS={0:RoboTwinClient('astra-vision-agent','http://127.0.0.1:8768',token=(OLD/'access.token').read_text().strip()),
             1:RoboTwinClient('astra-vision-agent','http://127.0.0.1:8769')}
    a.CURRENT=STATES[100000]
    # Migrate only with the original physical state intact.
    snap=CLIENTS[0].observe(False)['snapshot']
    assert snap['action_count']==STATES[100000]['action_count']
    while any('result' not in state for state in STATES.values()):
        ROUND+=1
        any_progress=False
        for seed in ORDER:
            if 'result' in STATES[seed]:continue
            try:
                visit(seed)
                any_progress=True
            except Exception as error:
                state=STATES[seed]
                state['episode_status']='infrastructure_pending'
                state['last_error']=str(error)
                a.CURRENT=state
                persist()
                a.append(ROOT/'infrastructure-errors.jsonl',{'time':time.time(),'seed':seed,'round':ROUND,
                         'error':str(error),'traceback':traceback.format_exc()})
                progress('infrastructure_pending')
        if not any_progress:time.sleep(30)
    progress('complete')
    a.save(ROOT/'summary.json',{'status':'complete','completed':20,
           'successes':sum(x['result']['success'] for x in STATES.values()),
           'episode_step_limit':None,'episode_time_limit_s':None,
           'results':[STATES[seed]['result'] for seed in SEEDS]})

if __name__=='__main__':main()
