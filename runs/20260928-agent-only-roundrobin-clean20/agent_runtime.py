"""Visual-agent inference and EEF command execution, with no learned action policy."""
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
    raise RuntimeError('Driver must install its progress writer')

def persist():
    save(ROOT / 'driver-state.json', CURRENT)

def fresh():
    observation = CLIENT.observe(False)
    snap = observation.get('snapshot', {})
    if snap:
        assert snap['episode_step_limit'] is None
        assert snap['episode_time_limit_s'] is None
        assert snap['policy_mode'] == 'agent_only' and snap['dp_enabled'] is False
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
    if kind not in ('eef','switch','checkpoint','finish'):
        raise ValueError('Agent-only driver forbids policy calls or episode resets')
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
    if receipt['status'] == 'failed' and pending['kind'] != 'eef':
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
    assert value['kind'] == 'eef' and 1 <= len(value['steps']) <= 8
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
               'episode_action_limit': None, 'episode_time_limit': None,
               'control_mode': 'agent_only; no DP/VLA available; no pre-approach by another policy'}
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
