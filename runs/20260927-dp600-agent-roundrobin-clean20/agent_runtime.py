"""Twenty scene-paired, unbounded episodes: real RGB agent + fixed DP600."""
from pathlib import Path
import base64, fcntl, hashlib, json, os, shutil, subprocess, time, traceback
import urllib.request
from PIL import Image, ImageDraw
from client import RoboTwinClient

ROOT = Path(__file__).resolve().parent
SEEDS = list(range(100000, 100020))
CODEX = '/home/aaa/.codex/packages/standalone/releases/0.156.1-x86_64-unknown-linux-musl/bin/codex'
MODEL = 'gpt-6-astra'
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
CLIENT = None
CURRENT = {}
RESULTS = []

def save(path, data):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    temporary.replace(path)

def append(path, data):
    with Path(path).open('a') as stream:
        stream.write(json.dumps(data, ensure_ascii=False, allow_nan=False) + '\n')

def progress(phase, **extra):
    value = {'status': phase, 'updated_at': time.time(), 'runner_pid': os.getpid(),
             'planned': len(SEEDS), 'completed': len(RESULTS),
             'successes': sum(x['success'] for x in RESULTS),
             'failures': sum(not x['success'] for x in RESULTS),
             'pending': len(SEEDS) - len(RESULTS), 'current_seed': CURRENT.get('seed'),
             'action_count': CURRENT.get('action_count', 0),
             'agent_decisions': CURRENT.get('decision_index', 0),
             'episode_step_limit': None, 'episode_time_limit_s': None, **extra}
    save(ROOT / 'progress.json', value)
    rows = ['# DP600 + 视觉 agent：20 局无时间与步数上限评估', '',
            f"状态：{phase}；已完成 {len(RESULTS)}/20；成功 {value['successes']}；失败 {value['failures']}；待完成 {value['pending']}。", '',
            '进行中的场景不记为失败；完成 20 局前不报告最终成功率。', '',
            f"当前 seed：{value['current_seed']}；动作数：{value['action_count']}；agent 决策数：{value['agent_decisions']}。", '',
            '模型：600.ckpt；视觉 agent：gpt-6-astra，max，Codex CLI 0.156.1。',
            '场景：demo_clean；种子：100000–100019，与纯 DP600 的 20 局配对。',
            '每局无时间、动作、接管次数或 agent 决策次数上限。',
            '每段 DP 6–120 个动作仅决定何时重新观察，不是整局上限。',
            '结束条件：官方成功判定，或判定器确认方块掉到地面（中心高度低于 0.30 m）。',
            '成功判定和掉落判定使用仿真状态；物体真值坐标不提供给决策 agent。',
            '网络、模型额度、仿真错误只记为基础设施问题，挂起并重试，不算任务失败。',
            '控制方式：600 整任务 DP 与视觉 agent 末端纠正交替执行；不是新训练的腕部 VLA，也不是残差融合。',
            'Agent 只接收三视角 RGB、机器人状态、动作回执及自身记忆。保存所有输入、JSON 决策和实际回执。',
            '三视角视频省略等待推理期间的静止画面，不能作为真实耗时；真实耗时另记。', '',
            '| seed | 结果 | 总动作 | agent 决策 | 原因 |', '|---|---|---:|---:|---|']
    for item in RESULTS:
        rows.append(f"| {item['seed']} | {'成功' if item['success'] else '失败'} | {item['action_count']} | {item['agent_decisions']} | {item['reason']} |")
    if phase == 'complete':
        rows.extend(['', f"最终结果：{value['successes']}/20，{value['successes']/20:.1%}。"])
    (ROOT / 'REPORT.md').write_text('\n'.join(rows) + '\n')

def persist():
    save(ROOT / 'driver-state.json', CURRENT)

def fresh():
    observation = CLIENT.observe(False)
    snap = observation.get('snapshot', {})
    if snap:
        assert snap['episode_step_limit'] is None
        assert snap['episode_time_limit_s'] is None
        if snap['seed'] == CURRENT.get('seed'):
            CURRENT['action_count'] = snap['action_count']
    return observation

def wait_command(receipt):
    # Network polling has no robot action or episode timeout.
    while receipt['status'] in ('queued', 'running'):
        time.sleep(1)
        receipt = CLIENT.request('/v1/commands/' + receipt['command_id'])
        fresh()
        progress('executing', command_id=receipt['command_id'])
    return receipt

def perform(kind, steps=None, actions=12, seed=100000):
    # Save the exact request before submission. Retrying an interrupted HTTP
    # request reuses the command ID and observation, so it cannot act twice.
    pending = CURRENT.get('pending_command')
    if pending is None:
        observation = fresh()
        if observation['busy']:
            receipt = CLIENT.request('/v1/commands/' + observation['active_command'])
            wait_command(receipt)
            observation = fresh()
        import uuid
        pending = {'client_id': CLIENT.client_id, 'command_id': str(uuid.uuid4()),
                   'epoch': observation['epoch'], 'revision': observation['revision'],
                   'kind': kind, 'steps': steps or [], 'max_actions': actions, 'seed': seed}
        CURRENT['pending_command'] = pending
        persist()
    receipt = wait_command(CLIENT.request('/v1/commands', pending))
    append(ROOT / 'commands.jsonl', {'time': time.time(), 'seed': CURRENT['seed'],
                                   'command': pending, 'receipt': receipt})
    CURRENT['pending_command'] = None
    persist()
    if receipt['status'] == 'failed' and pending['kind'] not in ('dp','eef'):
        raise RuntimeError('Simulator command failed: ' + json.dumps(receipt))
    return receipt

def capture(directory):
    observation = CLIENT.save_views(directory)
    canvas = Image.new('RGB', (960, 268), 'white')
    draw = ImageDraw.Draw(canvas)
    for index, name in enumerate(['head', 'left_wrist', 'right_wrist']):
        canvas.paste(Image.open(directory / (name + '.jpg')).convert('RGB'), (index*320, 28))
        draw.text((index*320+6, 8), name.upper(), fill='black')
    canvas.save(directory / 'three-views.jpg', quality=95)
    return observation

def validate_decision(value):
    import jsonschema
    jsonschema.validate(value, json.loads((ROOT / 'decision.schema.json').read_text()))
    if value['kind'] == 'eef' and not 1 <= len(value['steps']) <= 8:
        raise ValueError('EEF decision requires 1–8 steps')
    if value['kind'] == 'dp' and value['steps']:
        raise ValueError('DP decision must not contain EEF steps')
    return value

def infer():
    CURRENT['inference_attempt'] = CURRENT.get('inference_attempt', 0) + 1
    persist()
    directory = ROOT / 'episodes' / str(CURRENT['seed']) / f"decision-{CURRENT['decision_index']:05d}-attempt-{CURRENT['inference_attempt']:05d}"
    directory.mkdir(parents=True, exist_ok=False)
    observation = capture(directory)
    if observation['busy']:
        raise RuntimeError('Only infer from a stationary command boundary')
    snap = observation['snapshot']
    # Explicit input allowlist: no scene seed, files, object state, or credentials.
    proprio = {key: snap[key] for key in ['coordinates', 'left_eef', 'right_eef',
              'left_joints', 'right_joints', 'left_gripper_target', 'right_gripper_target']}
    payload = {'task': 'Stack the green block on the red block; release both grippers.',
               'robot': proprio, 'memory': CURRENT.get('memory', ''),
               'recent_actions': CURRENT.get('history', [])[-12:],
               'image_order': 'Optional previous composite first, then CURRENT head, left wrist, right wrist.',
               'episode_action_limit': None, 'episode_time_limit': None}
    prompt = 'Choose the next robot command from the supplied current RGB observations.\n' + json.dumps(payload, ensure_ascii=False)
    (directory / 'prompt.txt').write_text(prompt)
    args = [CODEX, 'exec', '--ignore-user-config', '--ephemeral', '--skip-git-repo-check',
            '--sandbox', 'read-only', '--model', MODEL, '--json', '--color', 'never',
            '-c', 'model_reasoning_effort="max"', '-c', 'approval_policy="never"',
            '-c', 'web_search="disabled"', '-c', 'project_doc_max_bytes=0',
            '-c', 'model_instructions_file=' + json.dumps(str(ROOT / 'agent-instructions.md')),
            '--disable', 'shell_tool', '--disable', 'unified_exec', '--disable', 'multi_agent',
            '--disable', 'plugins', '--disable', 'skill_search', '--enable', 'skip_host_skill_discovery',
            '--output-schema', str(ROOT / 'decision.schema.json'),
            '--output-last-message', str(directory / 'decision.json'), '-C', str(ROOT / 'agent-workspace')]
    previous = CURRENT.get('previous_views')
    if previous and Path(previous).is_file():
        args += ['--image', previous]
    for name in ['head', 'left_wrist', 'right_wrist']:
        args += ['--image', str(directory / (name + '.jpg'))]
    args += ['-']
    save(directory / 'invocation.json', {'args': args, 'input_observation_revision': observation['revision']})
    started = time.time()
    with (directory / 'events.jsonl').open('w') as stdout, (directory / 'stderr.log').open('w') as stderr:
        process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=stdout, stderr=stderr, text=True)
        process.stdin.write(prompt)
        process.stdin.close()
        while process.poll() is None:
            progress('agent_thinking', inference_pid=process.pid,
                     inference_elapsed_s=round(time.time()-started, 1))
            time.sleep(5)
    save(directory / 'runtime.json', {'exit_code': process.returncode, 'elapsed_s': time.time()-started})
    # Discard any decision if the model attempted filesystem, network, or other
    # tool access: such a turn does not qualify as the intended visual agent.
    for line in (directory / 'events.jsonl').read_text().splitlines():
        event = json.loads(line)
        item = event.get('item', {})
        if item.get('type') in ['command_execution','mcp_tool_call','web_search','file_change','collab_tool_call']:
            raise RuntimeError('Agent attempted a forbidden tool: ' + item['type'])
    if process.returncode:
        raise RuntimeError(f'Visual inference exited {process.returncode}; see {directory}/stderr.log')
    value = validate_decision(json.loads((directory / 'decision.json').read_text()))
    # Stale inference is never allowed to control a changed scene.
    live = fresh()
    if live['revision'] != observation['revision'] or live['epoch'] != observation['epoch']:
        raise RuntimeError('Observation changed during inference; discard decision')
    return value, str(directory / 'three-views.jpg')

def main():
    global CURRENT, RESULTS, CLIENT
    lock_stream = (ROOT / 'driver.lock').open('w')
    fcntl.flock(lock_stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    (ROOT / 'agent-workspace').mkdir(exist_ok=True)
    path = ROOT / 'episodes.jsonl'
    if path.exists():
        RESULTS = [json.loads(line) for line in path.read_text().splitlines() if line]
    saved = ROOT / 'driver-state.json'
    CURRENT = json.loads(saved.read_text()) if saved.exists() else {}
    while not (ROOT / 'access.token').exists():
        progress('initializing_simulator')
        time.sleep(2)
    CLIENT = RoboTwinClient('astra-vision-agent', 'http://127.0.0.1:8768')
    while True:
        try:
            observation = fresh()
            if observation['ready']:
                if observation['owner'] != CLIENT.client_id:
                    CLIENT.claim(takeover=True)
                    CLIENT.wait_hold()
                break
        except Exception:
            progress('initializing_simulator')
        time.sleep(2)
    for seed in SEEDS:
        if any(item['seed'] == seed for item in RESULTS):
            continue
        if CURRENT.get('seed') != seed:
            (ROOT / 'episodes' / str(seed)).mkdir(parents=True, exist_ok=True)
            CURRENT = {'seed': seed, 'started_at': time.time(), 'decision_index': 0,
                       'inference_attempt': 0, 'history': [], 'memory': '',
                       'action_count': 0, 'warmup_done': False}
            persist()
        while True:
            try:
                observation = fresh()
                if observation['snapshot']['seed'] != seed:
                    perform('reset', seed=seed)
                    observation = fresh()
                terminal = observation['snapshot']
                if terminal['task_success'] or terminal['terminal_failure']:
                    receipt = perform('finish')
                    item = {'seed': seed, 'success': terminal['task_success'],
                            'reason': 'official_success' if terminal['task_success'] else terminal['terminal_failure']['reason'],
                            'action_count': terminal['action_count'], 'agent_decisions': CURRENT['decision_index'],
                            'wall_time_s': time.time()-CURRENT['started_at'], 'video': receipt['video'],
                            'step_limit': None, 'time_limit_s': None}
                    save(ROOT / 'episodes' / str(seed) / 'result.json', item)
                    append(path, item)
                    RESULTS.append(item)
                    progress('episode_completed', last_episode=item)
                    break
                if not CURRENT['warmup_done']:
                    progress('initial_dp_rollout')
                    receipt = perform('dp', actions=120)
                    CURRENT['history'].append({'kind':'dp', 'reason':'Initial DP observation interval', 'receipt':receipt})
                    CURRENT['warmup_done'] = True
                    persist()
                    continue
                # Recover an issued command after process interruption before
                # requesting any new action from the model.
                if CURRENT.get('pending_decision') is None:
                    decision, views = infer()
                    CURRENT['pending_decision'] = {'decision': decision, 'views': views}
                    persist()
                pending = CURRENT['pending_decision']
                decision = pending['decision']
                receipt = perform(decision['kind'], decision['steps'], decision['dp_actions'])
                CURRENT['history'].append({'decision':decision, 'receipt':receipt})
                CURRENT['history'] = CURRENT['history'][-12:]
                CURRENT['memory'] = decision['memory']
                CURRENT['previous_views'] = pending['views']
                CURRENT['decision_index'] += 1
                CURRENT['pending_decision'] = None
                persist()
                append(ROOT / 'decisions.jsonl', {'time':time.time(), 'seed':seed,
                       'index':CURRENT['decision_index'], 'decision':decision, 'receipt':receipt})
                progress('observing')
            except Exception as error:
                append(ROOT / 'infrastructure-errors.jsonl', {'time':time.time(), 'seed':seed,
                       'error':str(error), 'traceback':traceback.format_exc()})
                progress('infrastructure_retry', error=str(error))
                # This is a service retry delay, not an episode deadline.
                time.sleep(30)
    progress('complete')
    save(ROOT / 'summary.json', {'status':'complete', 'planned':20, 'completed':20,
         'successes':sum(x['success'] for x in RESULTS),
         'success_rate':sum(x['success'] for x in RESULTS)/20,
         'step_limit':None, 'time_limit_s':None, 'episodes':RESULTS})

if __name__ == '__main__':
    main()
