"""Pure-agent control from initial state; preserve 20 scenes across visits."""
from pathlib import Path
import fcntl
import json
import os
import time
import traceback
import agent_runtime as a
from client import RoboTwinClient

ROOT = Path(__file__).resolve().parent
SEEDS = list(range(100000, 100020))
STATES = {}
ROUND = 0


def persist():
    a.save(ROOT / 'states' / f"{a.CURRENT['seed']}.json", a.CURRENT)


def progress(phase, **extra):
    if a.CURRENT.get('seed') in STATES:
        STATES[a.CURRENT['seed']] = a.CURRENT
    rows = []
    for seed in SEEDS:
        state = STATES[seed]
        rows.append({'seed': seed, 'status': state.get('episode_status', 'not_started'),
                     'visits': state.get('visits', 0), 'action_count': state.get('action_count', 0),
                     'agent_decisions': state.get('decision_index', 0),
                     'success': state.get('result', {}).get('success'),
                     'error': state.get('last_error')})
    completed = sum(x['success'] is not None for x in rows)
    successes = sum(x['success'] is True for x in rows)
    failures = sum(x['success'] is False for x in rows)
    value = {'status': phase, 'updated_at': time.time(), 'runner_pid': os.getpid(),
             'control_mode': 'agent_only', 'dp_enabled': False, 'initial_dp_actions': 0,
             'round': ROUND, 'planned': 20, 'started': sum(x['visits'] > 0 for x in rows),
             'completed': completed, 'successes': successes, 'failures': failures,
             'pending': 20-completed, 'current_seed': a.CURRENT.get('seed'),
             'action_count': a.CURRENT.get('action_count', 0),
             'agent_decisions': a.CURRENT.get('decision_index', 0),
             'episode_step_limit': None, 'episode_time_limit_s': None,
             'decisions_per_visit': 1, 'scenes': rows, **extra}
    a.save(ROOT / 'progress.json', value)
    lines = ['# 纯视觉 Agent：20 局轮转评估', '',
             f'状态：{phase}；第 {ROUND} 轮；已开始 {value["started"]}/20 局。',
             f'成功 {successes}；终止失败 {failures}；未完成 {20-completed}。', '',
             '从原始初始位置开始；DP 初始动作 0 步；无 DP/VLA 调用或回退。',
             '模型 gpt-6-astra / max，输入主摄与左右腕 RGB、机器人状态、执行回执和保存的记忆。',
             '保持原 Agent 动作接口：XYZ 5/20/50 mm 位移和夹爪开合；保持当前末端姿态，不能主动旋转。',
             '每局每轮执行一次 Agent 决策，最多 8 条末端指令；单次批量大小不是整局动作上限。',
             '整局无时间、动作、重试或决策次数上限；未完成状态保存后继续轮转。',
             '仅官方成功或方块落地结束一局；基础设施异常不计任务失败。',
             '20 个正式种子 100000–100019；demo_clean；验证种子 999010/999011 不纳入。',
             '物体真值仅用于保存/恢复和终止判定，不提供给 Agent。',
             '物理恢复验证位置、速度、关节驱动、夹爪和 RNG；内部求解器缓存和渲染噪声不保证逐位一致。',
             '视频直接标 AGENT 或 SYSTEM，并逐帧记录 command_id，便于对齐指令。', '',
             '| seed | 状态 | 轮转访问 | 动作计数 | Agent 决策 |', '|---|---|---:|---:|---:|']
    for row in rows:
        lines.append(f'| {row["seed"]} | {row["status"]} | {row["visits"]} | {row["action_count"]} | {row["agent_decisions"]} |')
    lines += ['', '尚未完成的局不记为失败；全部终止后才计算最终 20 局成功率。']
    (ROOT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


a.persist = persist
a.progress = progress


def select(seed):
    a.CURRENT = STATES[seed]
    obs = a.fresh()
    if obs['owner'] != a.CLIENT.client_id:
        a.CLIENT.claim(takeover=True)
        a.CLIENT.wait_hold()
    obs = a.fresh()
    if obs['snapshot']['seed'] != seed:
        pending = a.CURRENT.get('pending_command')
        if pending and pending['kind'] != 'switch':
            raise RuntimeError('Unresolved action receipt; preserve this scene before switching')
        progress('restoring_scene')
        a.perform('switch', seed=seed)
    obs = a.fresh()
    assert obs['snapshot']['seed'] == seed
    if not a.CURRENT.get('initial_observation_saved'):
        assert obs['snapshot']['action_count'] == 0, 'Pure-agent episode must begin before any action'
        a.CLIENT.save_views(ROOT / 'episodes' / str(seed) / 'initial')
        a.CURRENT['initial_observation_saved'] = True
        persist()


def finish_if_terminal():
    snap = a.fresh()['snapshot']
    if not (snap['task_success'] or snap['terminal_failure']):
        return False
    receipt = a.perform('finish')
    item = {'seed': a.CURRENT['seed'], 'success': snap['task_success'],
            'reason': 'official_success' if snap['task_success'] else snap['terminal_failure']['reason'],
            'action_count': snap['action_count'], 'agent_decisions': a.CURRENT['decision_index'],
            'visits': a.CURRENT['visits'], 'round': ROUND, 'dp_actions': 0,
            'step_limit': None, 'time_limit_s': None,
            'wall_time_s': time.time()-a.CURRENT['started_at'], 'final_video': receipt['video']}
    a.CURRENT['result'] = item
    a.CURRENT['episode_status'] = 'success' if item['success'] else 'failure'
    persist()
    a.save(ROOT / 'episodes' / str(a.CURRENT['seed']) / 'result.json', item)
    a.append(ROOT / 'episodes.jsonl', item)
    return True


def visit(seed):
    select(seed)
    state = a.CURRENT
    state['visits'] += 1
    state['episode_status'] = 'in_progress'
    state.pop('last_error', None)
    persist()
    if finish_if_terminal():
        return
    if state.get('pending_decision') is None:
        decision, views = a.infer()
        state['pending_decision'] = {'decision': decision, 'views': views}
        persist()
    pending = state['pending_decision']
    decision = pending['decision']
    assert decision['kind'] == 'eef'
    receipt = a.perform('eef', decision['steps'])
    state['history'].append({'decision': decision, 'receipt': receipt})
    state['history'] = state['history'][-12:]
    state['memory'] = decision['memory']
    state['previous_views'] = pending['views']
    state['decision_index'] += 1
    state['pending_decision'] = None
    persist()
    a.append(ROOT / 'decisions.jsonl', {'time': time.time(), 'seed': seed, 'round': ROUND,
             'index': state['decision_index'], 'decision': decision, 'receipt': receipt})
    if finish_if_terminal():
        return
    a.perform('checkpoint', seed=seed)
    state['episode_status'] = 'pending_next_round'
    persist()
    a.append(ROOT / 'visits.jsonl', {'time': time.time(), 'round': ROUND, 'seed': seed,
             'action_count': state['action_count'], 'agent_decisions': state['decision_index']})
    progress('yielding_to_next_scene')


def main():
    global ROUND, STATES
    lock = (ROOT / 'driver.lock').open('w')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert json.loads((ROOT / 'restore-verification.json').read_text())['passed']
    (ROOT / 'states').mkdir(exist_ok=True)
    (ROOT / 'agent-workspace').mkdir(exist_ok=True)
    for seed in SEEDS:
        path = ROOT / 'states' / f'{seed}.json'
        (ROOT / 'episodes' / str(seed)).mkdir(parents=True, exist_ok=True)
        state = json.loads(path.read_text()) if path.exists() else {
            'seed': seed, 'started_at': time.time(), 'decision_index': 0, 'inference_attempt': 0,
            'history': [], 'memory': '', 'action_count': 0, 'visits': 0, 'episode_status': 'not_started'}
        STATES[seed] = state
        a.save(path, state)
    schedule_path = ROOT / 'schedule.json'
    schedule = json.loads(schedule_path.read_text()) if schedule_path.exists() else {'round': 1, 'next_index': 0}
    a.CLIENT = RoboTwinClient('astra-agent-only', 'http://127.0.0.1:8770')
    a.CURRENT = STATES[SEEDS[schedule['next_index'] % len(SEEDS)]]
    while any('result' not in state for state in STATES.values()):
        ROUND = schedule['round']
        any_progress = False
        for index in range(schedule['next_index'], len(SEEDS)):
            seed = SEEDS[index]
            if 'result' not in STATES[seed]:
                try:
                    visit(seed)
                    any_progress = True
                except Exception as error:
                    state = STATES[seed]
                    state['episode_status'] = 'infrastructure_pending'
                    state['last_error'] = str(error)
                    a.CURRENT = state
                    persist()
                    a.append(ROOT / 'infrastructure-errors.jsonl', {'time': time.time(), 'seed': seed,
                             'round': ROUND, 'error': str(error), 'traceback': traceback.format_exc()})
                    progress('infrastructure_pending')
            schedule['next_index'] = index+1
            a.save(schedule_path, schedule)
        schedule = {'round': ROUND+1, 'next_index': 0}
        a.save(schedule_path, schedule)
        if not any_progress:
            time.sleep(30)
    progress('complete')
    results = [STATES[seed]['result'] for seed in SEEDS]
    a.save(ROOT / 'summary.json', {'status': 'complete', 'control_mode': 'agent_only', 'dp_actions': 0,
           'completed': 20, 'successes': sum(x['success'] for x in results),
           'success_rate': sum(x['success'] for x in results)/20,
           'episode_step_limit': None, 'episode_time_limit_s': None, 'results': results})


if __name__ == '__main__':
    main()
