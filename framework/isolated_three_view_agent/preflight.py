"""Check isolation and a scene-free inference before choosing the evaluation scene."""
from pathlib import Path
import json,subprocess,shutil,time
from isolation import preflight,model_command,audit_output

r=Path(__file__).resolve().parent
d=r/'preflight';inp=d/'input';out=d/'output';inp.mkdir(parents=True,exist_ok=True);out.mkdir(exist_ok=True)
(inp/'instructions.md').write_text('Return the JSON object {"ready":true}. Do not use tools. This is a transport and isolation check; no task observations are provided.\n')
(inp/'decision.schema.json').write_text(json.dumps({'type':'object','properties':{'ready':{'type':'boolean'}},'required':['ready'],'additionalProperties':False}))
boundary=preflight(inp,out);(d/'boundary.json').write_text(json.dumps(boundary,indent=2))
args=model_command(inp,out,[])
with (out/'events.jsonl').open('w') as stdout,(out/'stderr.log').open('w') as stderr:
    p=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=stdout,stderr=stderr,text=True)
    p.stdin.write('Return ready=true.');p.stdin.close();code=p.wait()
if code:raise RuntimeError(f'Preflight inference failed with exit code {code}')
audit=audit_output(out);assert json.loads((out/'decision.json').read_text())=={'ready':True}
(d/'result.json').write_text(json.dumps({'passed':True,'filesystem':boundary,'output_audit':audit,'scene_information_provided':False,'completed_at':time.time()},indent=2))
print('Scene-free model invocation and filesystem isolation passed.')
