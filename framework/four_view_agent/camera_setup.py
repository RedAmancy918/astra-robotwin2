"""Fixed fourth RGB camera; placement uses no object pose or task policy."""
import numpy as np
import sapien

CAMERA_NAME = 'oblique_camera'

def install_fourth_camera(task):
    target = np.array([0.0, 0.0, 0.8])
    horizontal_offset = np.array([0.65, 0.65, 0.0])
    horizontal_distance = np.linalg.norm(horizontal_offset)
    eye = target + horizontal_offset + np.array([0.0, 0.0, horizontal_distance])
    forward = target - eye
    forward /= np.linalg.norm(forward)
    left = np.cross([0.0, 0.0, 1.0], forward)
    left /= np.linalg.norm(left)
    up = np.cross(forward, left)
    transform = np.eye(4)
    transform[:3, :3] = np.stack([forward, left, up], axis=1)
    transform[:3, 3] = eye
    assert np.allclose(transform[:3, :3].T @ transform[:3, :3], np.eye(3))
    downward_angle = float(np.degrees(np.arctan2(-forward[2], np.linalg.norm(forward[:2]))))
    assert abs(downward_angle - 45.0) < 1e-8
    config = {'w': 1280, 'h': 960, 'fovy': 50.0}
    camera = task.scene.add_camera(name=CAMERA_NAME, width=config['w'], height=config['h'],
                                   fovy=np.radians(config['fovy']), near=0.05, far=10.0)
    camera.entity.set_pose(sapien.Pose(transform))
    task.cameras.static_camera_list.append(camera)
    task.cameras.static_camera_name.append(CAMERA_NAME)
    task.cameras.static_camera_config.append(config)
    return camera, {'name': CAMERA_NAME, 'position_world_m': eye.tolist(),
                    'look_at_world_m': target.tolist(), 'downward_angle_degrees': downward_angle,
                    'azimuth_position_degrees': 45.0, 'width': 1280, 'height': 960,
                    'vertical_fov_degrees': 50.0, 'placement_uses_object_ground_truth': False}
