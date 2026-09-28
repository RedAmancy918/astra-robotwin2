"""Private simulator snapshots. Never send these states to the visual agent."""
import copy, hashlib, pickle, random
import numpy as np
import sapien
import torch

def pose_value(pose):
    return np.r_[pose.p, pose.q].copy()

def pose_from(value):
    return sapien.Pose(value[:3], value[3:])

def rigid(block):
    return next(c for c in block.actor.get_components()
                if isinstance(c, sapien.physx.PhysxRigidDynamicComponent))

def physical(task):
    value = {'blocks': {}, 'robots': {}, 'grippers': {},
             'action_count': task.take_action_cnt, 'success': task.eval_success}
    for name in ['block1', 'block2']:
        block = getattr(task, name)
        body = rigid(block)
        value['blocks'][name] = {'pose': pose_value(block.get_pose()),
                               'velocity': body.get_linear_velocity().copy(),
                               'angular_velocity': body.get_angular_velocity().copy()}
    for arm in ['left', 'right']:
        art = getattr(task.robot, arm + '_entity')
        value['robots'][arm] = {
            'root_pose': pose_value(art.get_root_pose()),
            'root_velocity': art.get_root_linear_velocity().copy(),
            'root_angular_velocity': art.get_root_angular_velocity().copy(),
            'qpos': art.get_qpos().copy(), 'qvel': art.get_qvel().copy(),
            'qacc': art.get_qacc().copy(), 'qf': art.get_qf().copy(),
            'drives': [(j.get_drive_target().copy(), j.get_drive_velocity_target().copy())
                       for j in art.get_active_joints()]}
        value['grippers'][arm] = float(getattr(task.robot, arm + '_gripper_val'))
    return value

def obs_hash(observations):
    digest = hashlib.sha256()
    if observations is None:
        return None
    for queue in observations:
        digest.update(str(len(queue)).encode())
        for obs in queue:
            for key in sorted(obs):
                item = np.asarray(obs[key])
                digest.update(key.encode() + str(item.shape).encode() + item.tobytes())
    return digest.hexdigest()

def capture(sim):
    observations = copy.deepcopy(sim.dp_model.runner.obs_list) if sim.dp_model else None
    return {'seed': sim.seed, 'physical': physical(sim.task),
            'observations': observations, 'obs_hash': obs_hash(observations),
            'dp_dirty': sim.dp_dirty, 'numpy_rng': np.random.get_state(),
            'python_rng': random.getstate(), 'torch_rng': torch.get_rng_state(),
            'cuda_rng': torch.cuda.get_rng_state_all() if torch.cuda.is_initialized() else None}

def apply(sim, value):
    task = sim.task
    state = value['physical']
    for name, block_value in state['blocks'].items():
        block = getattr(task, name)
        block.actor.set_pose(pose_from(block_value['pose']))
        body = rigid(block)
        body.set_linear_velocity(block_value['velocity'])
        body.set_angular_velocity(block_value['angular_velocity'])
    for arm, data in state['robots'].items():
        art = getattr(task.robot, arm + '_entity')
        art.set_root_pose(pose_from(data['root_pose']))
        art.set_qpos(data['qpos'])
        art.set_qvel(data['qvel'])
        art.set_qacc(data['qacc'])
        art.set_qf(data['qf'])
        art.set_root_linear_velocity(data['root_velocity'])
        art.set_root_angular_velocity(data['root_angular_velocity'])
        joints = art.get_active_joints()
        assert len(joints) == len(data['drives'])
        for joint, (target, velocity) in zip(joints, data['drives']):
            joint.set_drive_target(target)
            joint.set_drive_velocity_target(velocity)
        setattr(task.robot, arm + '_gripper_val', state['grippers'][arm])
    task.take_action_cnt = state['action_count']
    task.eval_success = state['success']
    task.step_lim = None
    if value['observations'] is not None:
        if sim.dp_model is None:
            raise RuntimeError('Cannot restore a DP history without the loaded policy')
        sim.dp_model.runner.obs_list = copy.deepcopy(value['observations'])
    elif sim.dp_model:
        sim.dp_model.reset()
    sim.dp_dirty = value['dp_dirty'] if value['observations'] is not None else True
    np.random.set_state(value['numpy_rng'])
    random.setstate(value['python_rng'])
    torch.set_rng_state(value['torch_rng'])
    if value['cuda_rng'] is not None:
        torch.cuda.set_rng_state_all(value['cuda_rng'])
    task.scene.update_render()

def max_error(a, b):
    if isinstance(a, dict):
        assert set(a) == set(b)
        return max([max_error(a[k], b[k]) for k in a] + [0.])
    if isinstance(a, (list, tuple)):
        assert len(a) == len(b)
        return max([max_error(x, y) for x, y in zip(a,b)] + [0.])
    if isinstance(a, (np.ndarray, int, float, bool)):
        aa, bb = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
        assert aa.shape == bb.shape
        return float(np.max(np.abs(aa-bb))) if aa.size else 0.
    assert a == b
    return 0.

def verify(sim, value):
    # Renderer can sample new noise; verify simulator state and raw policy
    # observation history separately, not equality of freshly rendered pixels.
    expected=copy.deepcopy(value['physical'])
    actual=physical(sim.task)
    acceleration_cache_error=0.
    for arm in ['left','right']:
        # SAPIEN's own PhysxCpuSystem.pack/unpack persists position, velocity
        # and drive targets, but not this derived acceleration cache. Its
        # set_qacc API does not round-trip the solver's cached get_qacc value.
        acceleration_cache_error=max(acceleration_cache_error,
            max_error(expected['robots'][arm].pop('qacc'), actual['robots'][arm].pop('qacc')))
    error = max_error(expected,actual)
    history = obs_hash(sim.dp_model.runner.obs_list) if value['observations'] is not None else None
    rng_ok = (torch.equal(torch.get_rng_state(), value['torch_rng'])
              and pickle.dumps(np.random.get_state()) == pickle.dumps(value['numpy_rng'])
              and random.getstate() == value['python_rng'])
    if value['cuda_rng'] is not None:
        rng_ok = rng_ok and all(torch.equal(a,b) for a,b in zip(torch.cuda.get_rng_state_all(),value['cuda_rng']))
    result = {'physical_max_abs_error': error, 'history_equal': history == value['obs_hash'],
              'rng_equal': bool(rng_ok), 'action_count': sim.task.take_action_cnt,
              'derived_acceleration_cache_error': acceleration_cache_error,
              'derived_acceleration_cache_exact':False}
    if error > 1e-5 or not result['history_equal'] or not result['rng_equal']:
        raise RuntimeError('Restored episode failed verification: ' + str(result))
    return result
