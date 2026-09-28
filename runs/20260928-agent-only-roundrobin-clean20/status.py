from pathlib import Path
import json,time
r=Path(__file__).resolve().parent
p=json.loads((r/'progress.json').read_text())
p['heartbeat_age_s']=round(time.time()-p['updated_at'],1)
p['runner_alive']=Path('/proc/'+str(p['runner_pid'])).exists()
print(json.dumps(p,ensure_ascii=False,indent=2))
