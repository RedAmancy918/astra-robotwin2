"""Record requests and synchronized images for the interactive takeover experiment."""
from pathlib import Path
import json, sys, time, urllib.request
from PIL import Image, ImageDraw
urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({})))
RUN = Path(__file__).resolve().parent
sys.path.insert(0, str(RUN))
from client import RoboTwinClient

request = json.load(sys.stdin)
client = RoboTwinClient(request.get('client_id', 'vision-agent'), base_url='http://127.0.0.1:8767')
operation = request['operation']
if operation == 'claim':
    result = client.claim(takeover=True)
    result = client.wait_hold(timeout=20)
elif operation == 'command':
    obs = client.observe(False)
    assert not obs['busy'], 'Wait for active command or claim takeover first'
    assert obs['revision'] == request['expected_revision'], 'Observation revision changed'
    result = client.command(obs, request['kind'], request.get('steps'),
                            max_actions=request.get('max_actions', 12), seed=request.get('seed', 100000))
    if request.get('wait', False): result = client.wait(result, timeout=30)
elif operation == 'receipt':
    result = client.request('/v1/commands/' + request['command_id'])
elif operation == 'observe':
    obs = client.observe(False)
    target = RUN / 'observations' / f"r{obs['revision']:03d}-f{obs['snapshot']['frame_id']:06d}"
    result = client.save_views(target)
    canvas = Image.new('RGB', (960, 268), 'white')
    draw = ImageDraw.Draw(canvas)
    for i, name in enumerate(['head', 'left_wrist', 'right_wrist']):
        canvas.paste(Image.open(target / (name + '.jpg')).convert('RGB'), (i*320, 28))
        draw.text((i*320+6, 8), name, fill='black')
    canvas.save(target / 'three-views.jpg', quality=95)
    result['saved_views'] = str(target)
else:
    raise ValueError(operation)
with (RUN / 'agent-requests.jsonl').open('a') as f:
    f.write(json.dumps({'time': time.time(), 'request': request, 'response': result}, ensure_ascii=False) + '\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
