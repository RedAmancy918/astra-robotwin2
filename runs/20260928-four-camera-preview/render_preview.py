"""Restore the stopped scene and render four RGB views without any control step."""
from pathlib import Path
import os, sys, json, pickle, hashlib, time

HERE = Path(__file__).resolve().parent
SOURCE = Path('/mnt/data/yjh/astra-vla/runs/20260928-isolated-visual-eval01')
STOP = json.loads((SOURCE / 'stop-summary.json').read_text())
checkpoint = SOURCE / 'sim-checkpoints' / (str(STOP['checkpoint']['seed']) + '.pkl')
assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == STOP['checkpoint']['checkpoint_sha256']
saved = pickle.loads(checkpoint.read_bytes())
os.environ['ASTRA_VLA_AGENT_RUN'] = str(HERE)
os.environ['ASTRA_INITIAL_SEED'] = str(saved['seed'])
(HERE / 'videos').mkdir(exist_ok=True)
(HERE / 'viewer').mkdir(exist_ok=True)
sys.path.insert(0, str(SOURCE))
from server import Simulation
from scene_state import apply, verify, physical, max_error
from camera_setup import install_fourth_camera
from PIL import Image

class PreviewSimulation(Simulation):
    def start_video(self):
        pass

sim = PreviewSimulation()
apply(sim, saved)
restoration = verify(sim, saved)
before = physical(sim.task)
camera, config = install_fourth_camera(sim.task)
obs = sim.task.get_obs()
views = {'head': 'head_camera', 'left_wrist': 'left_camera',
         'right_wrist': 'right_camera', 'oblique': 'oblique_camera'}
for label, key in views.items():
    Image.fromarray(obs['observation'][key]['rgb']).save(HERE / 'viewer' / (label + '.png'))
after = physical(sim.task)
error = max_error(before, after)
assert error == 0.0, 'Rendering changed physical state'
metadata = {'created_at': time.time(), 'source_run': SOURCE.name,
            'source_checkpoint_sha256': hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            'restoration_verification': restoration, 'render_physical_state_max_abs_error': error,
            'control_actions_executed': 0, 'physics_steps_after_restore': sim.physics_step,
            'model_calls': 0, 'source_action_count': sim.task.take_action_cnt,
            'scene_state': 'User-stopped episode, restored without taking any new action',
            'fourth_camera': config,
            'image_sha256': {label: hashlib.sha256((HERE/'viewer'/(label+'.png')).read_bytes()).hexdigest() for label in views}}
(HERE / 'render-manifest.json').write_text(json.dumps(metadata, indent=2)+'\n')
print(json.dumps(metadata, indent=2), flush=True)
sim.task.close_env()
