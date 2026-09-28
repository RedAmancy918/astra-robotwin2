from pathlib import Path
import json, shutil, runner
class Replay:
 def observe(self, inline=False):
  v=json.loads((runner.ROOT/'preflight/observation.json').read_text())
  v['snapshot']['episode_step_limit']=None
  v['snapshot']['episode_time_limit_s']=None
  v['busy']=False
  return v
 def save_views(self,directory):
  for name in ['head.jpg','left_wrist.jpg','right_wrist.jpg']:
   shutil.copy2(runner.ROOT/'preflight'/name,directory/name)
  v=self.observe()
  runner.save(directory/'observation.json',v)
  return v
runner.CLIENT=Replay()
runner.CURRENT={'seed':'preflight','decision_index':0,'history':[],'memory':'Connectivity test only; your command will not be executed.'}
value, views=runner.infer()
runner.save(runner.ROOT/'preflight/result.json',{'decision':value,'views':views,'executed':False})
print(json.dumps(value,ensure_ascii=False),flush=True)
