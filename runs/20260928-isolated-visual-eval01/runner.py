"""One autonomous RGB/proprioception episode behind a curated model-input boundary."""
from pathlib import Path
import json, os, time, subprocess, hashlib, shutil, uuid, traceback, fcntl
from PIL import Image, ImageDraw
import jsonschema
from client import RoboTwinClient
from isolation import preflight,model_command,audit_output

ROOT=Path(__file__).resolve().parent
STATE={'decision_index':0,'memory':'','history':[],'action_count':0,'started_at':time.time()}
PROPRIO=['coordinates','left_tcp','right_tcp','left_joints','right_joints',
         'left_gripper_target','right_gripper_target']
ACTION_ERRORS={'Invalid TCP pose':'invalid_tcp_pose',
               'Quaternion must be normalized':'quaternion_not_normalized',
               'TCP outside workspace':'tcp_outside_workspace',
               'EEF target outside bridge workspace bounds':'eef_outside_workspace'}

def save(path,obj):
    p=Path(path);tmp=p.with_suffix(p.suffix+'.tmp')
    tmp.write_text(json.dumps(obj,indent=2,ensure_ascii=False,allow_nan=False)+'\n');tmp.replace(p)

def append(path,obj):
    with Path(path).open('a') as f:f.write(json.dumps(obj,ensure_ascii=False,allow_nan=False)+'\n')

def progress(status,**extra):
    save(ROOT/'progress.json',{'status':status,'updated_at':time.time(),'runner_pid':os.getpid(),
         'planned':1,'completed':0,'successes':0,'pending':1,'action_count':STATE['action_count'],
         'agent_decisions':STATE['decision_index'],'dp_actions':0,'control':'isolated_rgb_proprio_agent',
         'episode_step_limit':None,'episode_time_limit_s':None,**extra})

def verify_frozen():
    expected=json.loads((ROOT/'protocol.json').read_text())['frozen_files']
    for name,value in expected.items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=value:
            raise RuntimeError('Frozen evaluation file changed: '+name)

def sanitize_receipt(receipt):
    allowed=['arm','code','level','pose','actual_tcp','target_xyz','actual_xyz',
             'displacement_m','position_error_m','orientation_error_rad']
    steps=[]
    for step in receipt.get('steps',[]):
        val={key:step[key] for key in allowed if key in step}
        val['planning']=[{'arm':p['arm'],'status':p['status']} for p in step.get('planning',[])]
        steps.append(val)
    # Never expose errors containing server stack traces, filesystem paths or judge data.
    return {'status':receipt['status'],'steps':steps,
            'error_code':ACTION_ERRORS.get(receipt.get('error'))}

def infer(client):
    verify_frozen()
    d=ROOT/'decisions'/f'{STATE["decision_index"]:05d}';d.mkdir(parents=True,exist_ok=False)
    inp=d/'input';out=d/'output';inp.mkdir();out.mkdir()
    obs=client.save_views(d/'raw-observation')
    if obs['busy']:raise RuntimeError('Inference requires stationary observation')
    for name in ['head','left_wrist','right_wrist']:
        shutil.copyfile(d/'raw-observation'/(name+'.jpg'),inp/(name+'.jpg'))
    for name in ['instructions.md','decision.schema.json']:shutil.copyfile(ROOT/name,inp/name)
    images=[]
    if STATE.get('previous_views'):
        shutil.copyfile(STATE['previous_views'],inp/'previous.jpg');images.append('previous.jpg')
    images+=['head.jpg','left_wrist.jpg','right_wrist.jpg']
    payload={'task':'Stack the green block on the red block; release both grippers.',
             'robot':{k:obs['snapshot'][k] for k in PROPRIO},
             'memory':STATE['memory'],'recent_actions':STATE['history'][-12:],
             'image_order':images,'episode_action_limit':None,'episode_time_limit_s':None}
    save(inp/'prompt.json',payload)
    boundary=preflight(inp,out)
    boundary['input_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in inp.iterdir()}
    boundary['payload_fields']=list(payload)
    boundary['robot_fields']=list(payload['robot'])
    save(d/'input-boundary.json',boundary)
    args=model_command(inp,out,images)
    save(d/'invocation.json',{'args':args,'source_observation_revision':obs['revision']})
    with (out/'events.jsonl').open('w') as stdout,(out/'stderr.log').open('w') as stderr:
        p=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,text=True)
        p.stdin.write(json.dumps(payload));p.stdin.close()
        started=time.time()
        while p.poll() is None:
            progress('agent_thinking',inference_pid=p.pid,inference_elapsed_s=round(time.time()-started,1))
            time.sleep(5)
    save(d/'runtime.json',{'exit_code':p.returncode,'wall_time_s':time.time()-started})
    if p.returncode:raise RuntimeError('Isolated model invocation failed; inspect private diagnostic log')
    audit=audit_output(out);save(d/'output-audit.json',audit)
    decision=json.loads((out/'decision.json').read_text())
    jsonschema.validate(decision,json.loads((ROOT/'decision.schema.json').read_text()))
    for step in decision['steps']:
        if (step['code']=='POSE')!=(step['pose'] is not None):raise RuntimeError('Invalid pose/null combination')
    live=client.observe(False)
    if live['revision']!=obs['revision'] or live['epoch']!=obs['epoch']:
        raise RuntimeError('Stale inference rejected')
    canvas=Image.new('RGB',(960,268),'white');draw=ImageDraw.Draw(canvas)
    for i,name in enumerate(['head','left_wrist','right_wrist']):
        canvas.paste(Image.open(inp/(name+'.jpg')),(i*320,28));draw.text((i*320+5,5),name,fill='black')
    canvas.save(d/'previous-view-for-next-turn.jpg',quality=95)
    return decision,str(d/'previous-view-for-next-turn.jpg')

def main():
    lock=(ROOT/'driver.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    assert not (ROOT/'decisions.jsonl').exists(),'No resume into a fresh independent evaluation'
    assert json.loads((ROOT/'preflight/result.json').read_text())['passed']
    verify_frozen();progress('waiting_for_simulator')
    start=time.monotonic()
    while True:
        try:
            c=RoboTwinClient('isolated-rgb-agent','http://127.0.0.1:8773');obs=c.observe(False)
            if obs['ready']:break
        except Exception:
            if time.monotonic()-start>180:raise
        time.sleep(.5)
    assert obs['snapshot']['action_count']==0
    c.claim(takeover=True);c.wait_hold();c.save_views(ROOT/'initial')

    def perform(kind,steps=None):
        observation=c.observe(False)
        request={'client_id':c.client_id,'command_id':str(uuid.uuid4()),'epoch':observation['epoch'],
                 'revision':observation['revision'],'kind':kind,'steps':steps or []}
        append(ROOT/'requests.jsonl',request)
        receipt=c.request('/v1/commands',request)
        while receipt['status'] in ('queued','running'):
            time.sleep(.5);receipt=c.request('/v1/commands/'+receipt['command_id'])
            STATE['action_count']=c.observe(False)['snapshot']['action_count']
            progress('executing',command_id=receipt['command_id'])
        append(ROOT/'receipts.jsonl',receipt)
        STATE['action_count']=c.observe(False)['snapshot']['action_count']
        return receipt

    while True:
        snap=c.observe(False)['snapshot']
        if snap['task_success'] or snap['terminal_failure']:
            verification=perform('verify') if snap['task_success'] else None
            perform('checkpoint');final=c.save_views(ROOT/'final');finish=perform('finish')
            stable=bool(snap['task_success'] and verification and verification.get('stable_success'))
            result={'status':'complete','success':stable,'official_success':bool(snap['task_success']),
                    'reason':('official_stable_success' if stable else 'unstable_after_official_success') if snap['task_success'] else snap['terminal_failure']['reason'],
                    'stable_success':verification.get('stable_success') if verification else None,
                    'verification':verification,'action_count':STATE['action_count'],
                    'agent_decisions':STATE['decision_index'],'planned':1,'completed':1,
                    'dp_actions':0,'video':finish['video'],'controller':'isolated_rgb_proprio_agent',
                    'wall_time_s':time.time()-STATE['started_at'],'new_scene_not_selected_for_solvability':True,
                    'episode_step_limit':None,'episode_time_limit_s':None,'finished_at':time.time()}
            save(ROOT/'result.json',result)
            progress('complete',completed=1,successes=int(result['success']),pending=0,result=result)
            break
        decision,views=infer(c)
        receipt=perform('eef',decision['steps'])
        if receipt['status']=='failed' and receipt.get('error') not in ACTION_ERRORS:
            raise RuntimeError('Controller infrastructure error; not a task failure')
        STATE['history'].append({'decision':decision,'receipt':sanitize_receipt(receipt)})
        STATE['history']=STATE['history'][-12:];STATE['memory']=decision['memory'];STATE['previous_views']=views
        STATE['decision_index']+=1
        save(ROOT/'driver-state.json',STATE)
        append(ROOT/'decisions.jsonl',{'index':STATE['decision_index'],'decision':decision,'receipt':receipt,'time':time.time()})
        progress('decision_complete')

if __name__=='__main__':
    try:main()
    except Exception as error:
        save(ROOT/'infrastructure-error.json',{'error':str(error),'traceback':traceback.format_exc(),'time':time.time()})
        progress('infrastructure_pending',error=str(error))
        raise
