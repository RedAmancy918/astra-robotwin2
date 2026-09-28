"""Local, model-independent RoboTwin observation and control service."""
from pathlib import Path
import os, sys, json, time, threading, queue, secrets, hashlib, traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Literal
import numpy as np
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

ROOT = Path('/mnt/data/yjh/RoboTwin')
HERE = Path(__file__).resolve().parent
EXPERIMENT = Path('/mnt/data/yjh/robotwin_experiments/dp_stack_blocks_two')
CKPTS = ROOT/'XPolicyLab/policy/DP/checkpoints/yjh_dp50_clean-stack_blocks_two-aloha_agilex-joint-0'
os.chdir(ROOT)
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'XPolicyLab/policy/DP'))
TOKEN_PATH = HERE/'access.token'
if not TOKEN_PATH.exists():
    fd=os.open(TOKEN_PATH,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as f: f.write(secrets.token_urlsafe(32))
TOKEN=TOKEN_PATH.read_text().strip()
lock=threading.RLock()
commands=queue.Queue()
receipts={}
snapshot={}
frames={}
state={'ready':False,'owner':None,'epoch':0,'applied_epoch':0,'revision':0,
       'mode':'initializing','busy':False,'error':None,'active_command':None}

def log(event, **values):
    with open(HERE/'events.jsonl','a') as f:
        f.write(json.dumps({'time':time.time(),'event':event,**values},allow_nan=False)+'\n')

def auth(authorization: str=Header(default='')):
    if not secrets.compare_digest(authorization,'Bearer '+TOKEN):
        raise HTTPException(401,'Bearer token required (access.token on the server).')

app=FastAPI(title='RoboTwin three-camera control',version='1.0.0',dependencies=[Depends(auth)])

class Claim(BaseModel):
    client_id: str=Field(min_length=1,max_length=80)
    takeover: bool=False

class Step(BaseModel):
    arm: Literal['left','right']
    code: Literal['X+','X-','Y+','Y-','Z+','Z-','OPEN','CLOSE']
    level: Literal[1,2,3]=1

class Command(BaseModel):
    client_id: str
    command_id: str=Field(min_length=1,max_length=120)
    epoch: int
    revision: int
    kind: Literal['eef','dp','reset']
    steps: list[Step]=Field(default_factory=list,max_length=8)
    max_actions: int=Field(default=12,ge=1,le=120)
    seed: int=Field(default=1000,ge=0,le=10000000)

def status():
    with lock:
        return {**state,'snapshot':snapshot,'frame_age_s':None if not snapshot else round(time.time()-snapshot['captured_at'],3)}

@app.get('/v1/observe')
def observe(inline: bool=False):
    import base64
    with lock:
        value=status()
        if inline:
            value['images']={k:'data:image/jpeg;base64,'+base64.b64encode(v).decode() for k,v in frames.items()}
        return value

@app.get('/v1/frame/{camera}')
def frame(camera: Literal['head','left_wrist','right_wrist']):
    with lock:
        if camera not in frames: raise HTTPException(503,'Simulator is initializing.')
        return Response(frames[camera],media_type='image/jpeg',headers={'Cache-Control':'no-store','X-Frame-Id':str(snapshot['frame_id'])})

@app.post('/v1/control/claim')
def claim(req:Claim):
    with lock:
        if state['owner'] not in (None,req.client_id) and not req.takeover:
            raise HTTPException(409,'Another client owns control; set takeover=true to request handoff.')
        # Every claim creates a new generation: queued and in-flight older actions are invalid.
        state.update(owner=req.client_id,epoch=state['epoch']+1,mode='hold_requested')
        log('claim',client_id=req.client_id,epoch=state['epoch'])
        return status()

@app.post('/v1/control/hold')
def hold(req:Claim):
    with lock:
        if state['owner']!=req.client_id: raise HTTPException(409,'Only the owner can hold; claim with takeover first.')
        state.update(epoch=state['epoch']+1,mode='hold_requested')
        log('hold_requested',client_id=req.client_id,epoch=state['epoch'])
        return status()

@app.post('/v1/commands',status_code=202)
def submit(req:Command):
    data=req.model_dump()
    fingerprint=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest()
    with lock:
        if req.command_id in receipts:
            prior=receipts[req.command_id]
            if prior['fingerprint']!=fingerprint: raise HTTPException(409,'command_id reused with different content')
            return prior
        if not state['ready']: raise HTTPException(503,'Simulator is not ready.')
        if state['owner']!=req.client_id: raise HTTPException(409,'Control belongs to another client.')
        if req.epoch!=state['epoch'] or state['applied_epoch']!=state['epoch']:
            raise HTTPException(409,'Control generation is stale or hold is not applied yet; observe again.')
        if req.revision!=state['revision']: raise HTTPException(409,'Observation is stale; observe again.')
        if state['busy']: raise HTTPException(409,'A command is active; wait or hold/take over.')
        if req.kind=='eef' and not req.steps: raise HTTPException(422,'eef requires at least one step')
        if req.kind=='dp' and not list(CKPTS.glob('[0-9]*.ckpt')):
            raise HTTPException(409,'The first trained DP checkpoint is not available yet.')
        if snapshot.get('task_success') and req.kind!='reset': raise HTTPException(409,'Episode ended; reset first.')
        receipt={'command_id':req.command_id,'client_id':req.client_id,'status':'queued','fingerprint':fingerprint,'epoch':req.epoch,'submitted_at':time.time()}
        receipts[req.command_id]=receipt
        state.update(busy=True,active_command=req.command_id)
        commands.put(data)
        log('command_submitted',command=data)
        return receipt.copy()

@app.get('/v1/commands/{command_id}')
def receipt(command_id:str):
    with lock:
        if command_id not in receipts: raise HTTPException(404,'Unknown command')
        return receipts[command_id].copy()

@app.get('/v1/training')
def training():
    p=EXPERIMENT/'pipeline.status'
    metrics=EXPERIMENT/'training/logs.json.txt'
    latest=None
    if metrics.exists():
        with metrics.open('rb') as f:
            f.seek(max(0,metrics.stat().st_size-16384))
            lines=f.read().splitlines()
        for line in reversed(lines):
            try: latest=json.loads(line); break
            except ValueError: pass
    return {'status':p.read_text().strip() if p.exists() else 'preparing',
            'episodes':len(list((ROOT/'data/yjh_dp50_clean/stack_blocks_two/aloha_agilex/data').glob('*.hdf5'))),
            'metrics':latest,'checkpoints':sorted([p.name for p in CKPTS.glob('*.ckpt')])}

# The dashboard and schema reveal no robot state until a token is supplied.
@app.get('/',response_class=HTMLResponse,dependencies=[])
def dashboard(): return (HERE/'index.html').read_text()

class Simulation:
    def __init__(self):
        self.task=None
        self.last_publish=0.
        self.frame_id=0
        self.active_epoch=0
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='dp-inference')
        self.future=None
        self.dp_model=None
        self.dp_checkpoint=None
        self.reset(1000)

    def reset(self,seed):
        import yaml
        from envs.stack_blocks_two import stack_blocks_two
        if self.task is not None: self.task.close_env()
        cfg=yaml.safe_load((ROOT/'env_cfg/task_config/yjh_smoke.yml').read_text())
        mapping=yaml.safe_load((ROOT/'env_cfg/task_config/_embodiment_config.yml').read_text())
        robot=mapping[cfg['embodiment'][0]]['file_path']
        rcfg=yaml.safe_load((Path(robot)/'config.yml').read_text())
        cfg.update(task_name='stack_blocks_two',left_robot_file=robot,right_robot_file=robot,
            left_embodiment_config=rcfg,right_embodiment_config=rcfg,dual_arm_embodied=True,
            embodiment_name='aloha-agilex',eval_mode=True,save_data=False,render_freq=0,
            need_plan=True,eval_video_save_dir=None,eval_video_log=False)
        self.task=stack_blocks_two()
        self.task.setup_demo(now_ep_num=0,seed=seed,**cfg)
        self.task.step_lim=10000
        self.task.set_instruction('Stack the green block on the red block.')
        self.task.control_tick=self.tick
        self.seed=seed
        self.publish()

    def publish(self):
        from XPolicyLab.utils.process_data import encode_image_bit
        obs=self.task.get_obs()
        self.obs=obs
        cams={'head':'head_camera','left_wrist':'left_camera','right_wrist':'right_camera'}
        images={k:encode_image_bit(obs['observation'][v]['rgb'],quality=90) for k,v in cams.items()}
        r=self.task.robot
        self.frame_id+=1
        data={'frame_id':self.frame_id,'captured_at':time.time(),'seed':self.seed,
              'task':'stack_blocks_two','instruction':self.task.get_instruction(),
              'task_success':bool(self.task.eval_success),'coordinates':'world; metres; quaternion wxyz',
              'left_eef':r.get_left_ee_pose(),'right_eef':r.get_right_ee_pose(),
              'left_joints':list(map(float,r.get_left_arm_real_jointState())),'right_joints':list(map(float,r.get_right_arm_real_jointState())),
              'left_gripper_target':float(r.get_left_gripper_val()),'right_gripper_target':float(r.get_right_gripper_val()),
              'cameras':{k:{'url':'/v1/frame/'+k,'shape':list(obs['observation'][v]['rgb'].shape)} for k,v in cams.items()},
              'simulation':'stepped during actions; paused between commands'}
        with lock:
            snapshot.clear(); snapshot.update(data)
            frames.clear(); frames.update(images)
        self.last_publish=time.monotonic()

    def freeze(self):
        r=self.task.robot
        for arm in ('left','right'):
            q=getattr(r,f'get_{arm}_arm_real_jointState')()[:-1]
            r.set_arm_joints(q,np.zeros(len(q)),arm)

    def cancelled(self):
        with lock: return self.active_epoch!=state['epoch']

    def tick(self):
        if self.cancelled():
            self.freeze()
            return True
        if time.monotonic()-self.last_publish>0.4: self.publish()
        return False

    def infer(self,obs,checkpoint):
        import torch
        from model import Model
        from XPolicyLab.utils.process_data import pack_robot_state,get_robot_action_dim_info
        if self.dp_checkpoint!=str(checkpoint):
            self.dp_model=Model({'env_cfg_type':'aloha_agilex','bench_name':'yjh_dp50_clean',
                'task_name':'stack_blocks_two','ckpt_name':'stack_blocks_two','action_type':'joint',
                'seed':0,'model_path':str(CKPTS),'checkpoint_num':checkpoint.stem})
            self.dp_checkpoint=str(checkpoint)
        j=obs['joint_action']
        runtime={'env_idx':0,'vision':{k:{'color':obs['observation'][v]['rgb']} for k,v in
            [('cam_head','head_camera'),('cam_left_wrist','left_camera'),('cam_right_wrist','right_camera')]},
            'state':{'left_arm_joint_state':np.asarray(j['left_arm']), 'right_arm_joint_state':np.asarray(j['right_arm']),
                     'left_ee_joint_state':np.asarray([j['left_gripper']]),'right_ee_joint_state':np.asarray([j['right_gripper']])}}
        with torch.inference_mode():
            self.dp_model.update_obs(runtime)
            actions=self.dp_model.get_action()
        info=get_robot_action_dim_info('aloha_agilex')
        return [pack_robot_state({'state':a},'joint',info) for a in actions]

    def wait_inference(self,future):
        while not future.done():
            if self.cancelled(): return None
            if time.monotonic()-self.last_publish>0.4: self.publish()
            time.sleep(0.02)
        return future.result()

    def execute(self,c):
        self.active_epoch=c['epoch']
        if self.cancelled(): return 'cancelled',{}
        if c['kind']=='reset':
            if self.future and not self.future.done(): raise RuntimeError('Previous inference is draining; retry reset shortly.')
            self.reset(c['seed'])
            return ('cancelled' if self.cancelled() else 'completed'),{}
        if c['kind']=='eef':
            results=[]
            for step in c['steps']:
                if self.cancelled(): break
                r=self.task.robot
                left=np.array(r.get_left_ee_pose()); right=np.array(r.get_right_ee_pose())
                lg=float(r.get_left_gripper_val()); rg=float(r.get_right_gripper_val())
                target=left if step['arm']=='left' else right
                start=target[:3].copy()
                code=step['code']
                if code in ('OPEN','CLOSE'):
                    value=1. if code=='OPEN' else 0.
                    if step['arm']=='left': lg=value
                    else: rg=value
                else:
                    axis='XYZ'.index(code[0]); delta={1:0.005,2:0.02,3:0.05}[step['level']]
                    target[axis]+=delta*(1 if code[1]=='+' else -1)
                    if np.any(target[:3]<[-0.7,-0.65,0.62]) or np.any(target[:3]>[0.7,0.6,1.6]):
                        raise ValueError('EEF target outside bridge workspace bounds')
                self.task.take_action(np.r_[left,lg,right,rg],action_type='ee')
                actual=np.asarray(getattr(r,f"get_{step['arm']}_ee_pose")())[:3]
                residual=float(np.linalg.norm(actual-target[:3]))
                results.append({**step,'target_xyz':target[:3].tolist(),'actual_xyz':actual.tolist(),
                                'displacement_m':(actual-start).tolist(),'position_error_m':residual})
                if self.cancelled(): break
                if residual>0.008: return 'target_not_reached',{'steps':results}
            return ('cancelled' if self.cancelled() else 'completed'),{'steps':results}
        if self.future and not self.future.done(): raise RuntimeError('Previous DP inference is draining; retry shortly.')
        if self.dp_model: self.dp_model.reset()
        checkpoint=max(CKPTS.glob('[0-9]*.ckpt'),key=lambda p:int(p.stem))
        count=0
        while count<c['max_actions'] and not self.cancelled() and not self.task.eval_success:
            self.publish()
            self.future=self.executor.submit(self.infer,self.obs,checkpoint)
            actions=self.wait_inference(self.future)
            if actions is None: break
            for action in actions:
                if self.cancelled() or count>=c['max_actions'] or self.task.eval_success: break
                if not np.isfinite(action).all(): raise ValueError('DP produced non-finite action')
                self.task.take_action(action,action_type='qpos')
                count+=1
        return ('cancelled' if self.cancelled() else 'completed'),{'actions_executed':count,'checkpoint':self.dp_checkpoint}

    def run(self):
        with lock: state.update(ready=True,mode='hold')
        while True:
            with lock: needs_hold=state['epoch']!=state['applied_epoch']
            if needs_hold:
                self.freeze()
                with lock: state.update(applied_epoch=state['epoch'],mode='hold')
                self.publish()
            try: c=commands.get(timeout=0.15)
            except queue.Empty:
                if time.monotonic()-self.last_publish>0.8: self.publish()
                continue
            cid=c['command_id']
            with lock:
                receipts[cid].update(status='running',started_at=time.time())
                state['mode']=c['kind']
            try: result,detail=self.execute(c)
            except Exception as exc:
                traceback.print_exc()
                result,detail='failed',{'error':str(exc)}
            self.freeze()
            self.publish()
            with lock:
                state['revision']+=1
                state.update(busy=False,active_command=None,mode='hold',applied_epoch=state['epoch'])
                receipts[cid].update(status=result,finished_at=time.time(),revision=state['revision'],**detail)
                log('command_finished',receipt=receipts[cid])

if __name__=='__main__':
    import uvicorn, faulthandler, signal
    faulthandler.register(signal.SIGUSR1,all_threads=True)
    # Public HTML has no credentials or observation data; all /v1 endpoints use bearer auth.
    for route in app.routes:
        if getattr(route,'path',None)=='/': route.dependant.dependencies=[]
    try:
        print('Initializing simulator before starting HTTP threads',flush=True)
        simulation=Simulation()
        print('Simulator ready; starting HTTP service',flush=True)
        threading.Thread(target=lambda:uvicorn.run(app,host='127.0.0.1',port=8766,log_level='warning'),daemon=True).start()
        simulation.run()
    except Exception as exc:
        traceback.print_exc()
        with lock: state.update(error=str(exc),ready=False,mode='error')
        while True: time.sleep(10)
