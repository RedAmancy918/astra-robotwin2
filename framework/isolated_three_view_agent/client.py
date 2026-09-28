"""Small REST client usable from any AI tool runner; observations remain RGB."""
import os, json, time, uuid, urllib.request, urllib.error, base64
from pathlib import Path

class RoboTwinClient:
    def __init__(self,client_id,base_url='http://127.0.0.1:8766',token=None):
        self.client_id=client_id
        self.base_url=base_url.rstrip('/')
        self.token=token or os.environ.get('ROBOTWIN_TOKEN') or Path(__file__).with_name('access.token').read_text().strip()

    def request(self,path,body=None):
        data=None if body is None else json.dumps(body).encode()
        req=urllib.request.Request(self.base_url+path,data=data,headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=30) as response: return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f'{exc.code}: {exc.read().decode()}') from exc

    def observe(self,inline=True): return self.request('/v1/observe?inline='+str(inline).lower())

    def claim(self,takeover=False):
        result=self.request('/v1/control/claim',{'client_id':self.client_id,'takeover':takeover})
        return result

    def hold(self): return self.request('/v1/control/hold',{'client_id':self.client_id})

    def wait_hold(self,timeout=60):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            obs=self.observe(False)
            if obs['applied_epoch']==obs['epoch'] and not obs['busy']: return obs
            time.sleep(.1)
        raise TimeoutError('Hold was requested but has not been applied')

    def command(self,observation,kind,steps=None,max_actions=12,seed=1000,command_id=None):
        return self.request('/v1/commands',{'client_id':self.client_id,'command_id':command_id or str(uuid.uuid4()),
            'epoch':observation['epoch'],'revision':observation['revision'],'kind':kind,
            'steps':steps or [],'max_actions':max_actions,'seed':seed})

    def wait(self,receipt,timeout=180):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            result=self.request('/v1/commands/'+receipt['command_id'])
            if result['status'] not in ('queued','running'): return result
            time.sleep(.1)
        raise TimeoutError('Command still running; query receipt or request hold')

    def save_views(self,directory):
        obs=self.observe()
        target=Path(directory);target.mkdir(parents=True,exist_ok=True)
        for name,data in obs.pop('images',{}).items():
            (target/(name+'.jpg')).write_bytes(base64.b64decode(data.split(',',1)[1]))
        (target/'observation.json').write_text(json.dumps(obs,indent=2))
        return obs

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--save-views');p.add_argument('--client-id',default='reader');a=p.parse_args()
    c=RoboTwinClient(a.client_id)
    print(json.dumps(c.save_views(a.save_views) if a.save_views else c.observe(False),indent=2))
