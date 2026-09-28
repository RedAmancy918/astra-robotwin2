from pathlib import Path
import json, time
run = Path(__file__).resolve().parent
p = run / 'progress.json'
if p.exists():
    state = json.loads(p.read_text())
    state['heartbeat_age_s'] = round(time.time()-state['updated_at'],1)
    state['runner_alive'] = Path('/proc/' + str(state['runner_pid'])).exists()
    print(json.dumps(state,ensure_ascii=False,indent=2))
else:
    print('尚未启动')
