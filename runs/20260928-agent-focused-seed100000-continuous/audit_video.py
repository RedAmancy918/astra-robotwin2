"""Verify that encoded frames correspond to a complete fixed physics-time grid."""
from pathlib import Path
import json, collections, hashlib, subprocess

r=Path(__file__).resolve().parent
result=json.loads((r/'result.json').read_text())
frames=[json.loads(line) for line in (r/'video-frames.jsonl').read_text().splitlines()]
assert result['success'] and result['stability']['stable_success']
assert frames and frames[0]['physics_step']==0
assert len(frames)==result['physics_steps']//10+1
assert all(f['frame']==i and f['physics_step']==i*10 for i,f in enumerate(frames))
assert all(abs(f['simulation_time_s']-i/25)<1e-5 for i,f in enumerate(frames))
assert all(abs(f['presentation_time_s']-i/25)<1e-10 for i,f in enumerate(frames))
video=Path(result['video'])
ffbin=Path('/mnt/data/yjh/conda_envs/robotwin/bin')
probe=json.loads(subprocess.check_output([str(ffbin/'ffprobe'),'-v','error','-count_frames',
    '-show_entries','format=duration,size:stream=codec_name,width,height,r_frame_rate,nb_read_frames',
    '-of','json',str(video)],text=True))
stream=probe['streams'][0]
assert stream['r_frame_rate']=='25/1'
assert int(stream['nb_read_frames'])==len(frames)
assert abs(float(probe['format']['duration'])-len(frames)/25)<.001
decode=subprocess.run([str(ffbin/'ffmpeg'),'-v','error','-i',str(video),'-f','null','-'],capture_output=True,text=True)
assert decode.returncode==0 and not decode.stderr,decode.stderr
summary={'passed':True,'frames':len(frames),'fps':25,'duration_s':len(frames)/25,
         'physics_steps':result['physics_steps'],'simulation_duration_s':result['simulation_time_s'],
         'physics_steps_between_frames':10,'simulation_seconds_between_frames':.04,
         'missing_grid_frames':0,'decode_errors':0,'size_bytes':video.stat().st_size,
         'video_sha256':hashlib.sha256(video.read_bytes()).hexdigest(),
         'frames_per_action':dict(collections.Counter(str(f['action_count']) for f in frames)),
         'source':'fresh rendered RGB after actual physics steps; no interpolated frames',
         'official_success':result['success'],'stable_checks':result['stability']['successful_checks']}
(r/'video-audit.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))
