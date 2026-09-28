from pathlib import Path
import json,re,sys,time
project=Path(__file__).resolve().parents[1]
runs=sorted((project/'runs').iterdir())
if len(sys.argv)>1:
    runs=[project/'runs'/sys.argv[1]]
for run in runs:
    if not run.is_dir(): continue
    p=run/'progress.json'
    data=json.loads(p.read_text()) if p.exists() else {'status':'starting'}
    f=run/'evaluation.log'
    last_step=None
    if f.exists():
        with f.open('rb') as stream:
            stream.seek(max(0,f.stat().st_size-5000))
            tail=re.sub(r'\x1b\[[0-9;]*m','',stream.read().decode(errors='replace'))
        steps=re.findall(r'step:\s*(\d+)\s*/\s*(\d+)',tail)
        if steps: last_step=[int(n) for n in steps[-1]]
    pid_file=run/'launcher.pid'
    pid=pid_file.read_text().strip() if pid_file.exists() else None
    proc=Path(f'/proc/{pid}/cmdline')
    active=proc.exists() and b'run_eval.sh' in proc.read_bytes()
    print(json.dumps({'run':run.name,'status':data['status'],'launcher_active':active,
        'completed':data.get('completed',0),'planned':data.get('planned',20),
        'successes':data.get('successes',0),'last_observed_action_step':last_step,
        'last_episode':data.get('last_episode')},ensure_ascii=False,indent=2))
