"""Audited controller for a single scene; decisions are supplied by Codex after RGB inspection."""
from pathlib import Path
import json, sys, time
from client import RoboTwinClient
from PIL import Image, ImageDraw

r=Path(__file__).resolve().parent
c=RoboTwinClient('codex-focused-visual','http://127.0.0.1:8771')
request=json.load(sys.stdin)
obs=c.observe(False)
if obs['owner']!=c.client_id:
    c.claim(takeover=True)
    obs=c.wait_hold()
index=len(list((r/'actions').glob('[0-9]*'))) if (r/'actions').exists() else 0
d=r/'actions'/f'{index:04d}'
d.mkdir(parents=True,exist_ok=False)
(d/'request.json').write_text(json.dumps({'time':time.time(),'controller':'Codex supervised visual control','observation_revision':obs['revision'],**request},indent=2))
receipt=None
if request.get('kind') not in (None,'observe'):
    receipt=c.wait(c.command(obs,request['kind'],steps=request.get('steps'),seed=100000),timeout=600)
    (d/'receipt.json').write_text(json.dumps(receipt,indent=2))
obs=c.save_views(d)
canvas=Image.new('RGB',(960,268),'white');draw=ImageDraw.Draw(canvas)
for i,name in enumerate(['head','left_wrist','right_wrist']):
    canvas.paste(Image.open(d/(name+'.jpg')),(i*320,28));draw.text((i*320+5,5),name,fill='black')
canvas.save(d/'three-views.jpg',quality=95)
print(json.dumps({'action_dir':str(d),'receipt':receipt,'snapshot':{k:v for k,v in obs['snapshot'].items() if k not in ('camera_calibration','cameras','left_joints','right_joints')}},indent=2))
with (r/'commands.jsonl').open('a') as f:f.write(json.dumps({'time':time.time(),'request':request,'receipt':receipt,'action_dir':str(d)})+'\n')
(r/'progress.json').write_text(json.dumps({'updated_at':time.time(),'mode':'single_scene_supervised_visual','seed':100000,'dp_actions':0,'task_success':obs['snapshot']['task_success'],'action_count':obs['snapshot']['action_count'],'latest_action':str(d)},indent=2))
