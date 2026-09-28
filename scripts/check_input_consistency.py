"""Check sampled raw training frames against Zarr and the deployed DP adapter."""
from pathlib import Path
import sys, json
import h5py, zarr, numpy as np

root = Path('/mnt/data/yjh/RoboTwin')
sys.path[:0] = [str(root), str(root / 'XPolicyLab/policy/DP')]
from XPolicyLab.utils.process_data import decode_image_bit, get_robot_action_dim_info, pack_robot_state
from model import encode_obs

raw_path = root / 'data/yjh_dp50_clean/stack_blocks_two/aloha_agilex/data/episode_0000000.hdf5'
zarr_path = root / 'XPolicyLab/policy/DP/data/yjh_dp50_clean-stack_blocks_two-aloha_agilex-joint.zarr'
z = zarr.open(str(zarr_path), mode='r')
dims = get_robot_action_dim_info('aloha_agilex')
camera_map = [('cam_head', 'head_camera', 'head_cam'),
              ('cam_left_wrist', 'left_camera', 'left_cam'),
              ('cam_right_wrist', 'right_camera', 'right_cam')]
results = []
with h5py.File(raw_path, 'r') as h:
    for t in [0, 100, 323]:
        obs = {'vision': {}, 'state': {key[:-1]: value[t] for key, value in h['state'].items()}}
        frame = {'episode': 0, 'frame': t, 'cameras': {}}
        for raw_name, zarr_name, _ in camera_map:
            rgb = decode_image_bit(h[f'vision/{raw_name}/colors'][t])
            obs['vision'][raw_name] = {'color': rgb}
            reference = np.moveaxis(z[f'data/{zarr_name}'][t], 0, -1)
            diff = int(np.abs(rgb.astype(np.int16) - reference.astype(np.int16)).max())
            assert diff == 0, (t, raw_name, diff)
            frame['cameras'][raw_name] = {'HDF_vs_Zarr_max_pixel_difference': diff}
        encoded = encode_obs(obs, 'joint', dims)
        for raw_name, zarr_name, encoded_name in camera_map:
            diff = float(np.abs(encoded[encoded_name] - z[f'data/{zarr_name}'][t] / 255.0).max())
            assert diff < 1e-12, (t, raw_name, diff)
            frame['cameras'][raw_name]['DP_adapter_vs_Zarr_normalized_max_difference'] = diff
        state_diff = float(np.abs(encoded['agent_pos'] - z['data/state'][t]).max())
        action = pack_robot_state({'action': {key: value[t] for key, value in h['action'].items()}},
                                  'joint', dims, source_type='dataset', state_type='action')
        action_diff = float(np.abs(action - z['data/action'][t]).max())
        assert state_diff == 0 and action_diff == 0, (t, state_diff, action_diff)
        frame.update(state_max_difference=state_diff, action_max_difference=action_diff)
        results.append(frame)
report = {'status': 'passed', 'scope': '3 sampled frames of training episode 0; not an exhaustive dataset or live-simulator check',
          'raw_data': str(raw_path), 'training_data': str(zarr_path), 'checks': results}
output = Path('/mnt/data/yjh/astra-vla/records/training-dp50/input-consistency.json')
output.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
