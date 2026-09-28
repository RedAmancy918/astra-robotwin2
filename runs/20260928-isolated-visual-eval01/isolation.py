"""Build a clean filesystem namespace for each model call; no experiment root mount."""
from pathlib import Path
import subprocess, json, hashlib

CLI=Path('/home/aaa/.codex/packages/standalone/releases/0.156.1-x86_64-unknown-linux-musl/bin/codex')
AUTH=Path('/home/aaa/.codex/auth.json')

def sandbox(input_dir,output_dir,command,network=True):
    args=['bwrap','--unshare-user','--unshare-pid','--unshare-ipc','--unshare-uts',
          '--die-with-parent','--new-session','--clearenv']
    if not network:args+=['--unshare-net']
    for p in ['/usr','/bin','/lib','/lib64']:
        if Path(p).exists():args+=['--ro-bind',p,p]
    args+=['--proc','/proc','--dev','/dev','--tmpfs','/tmp','--dir','/etc']
    for p in ['/etc/ssl','/etc/resolv.conf','/etc/hosts','/etc/nsswitch.conf','/etc/ld.so.cache']:
        if Path(p).exists():args+=['--ro-bind',p,p]
    args+=['--dir','/app','--ro-bind',str(CLI),'/app/codex',
           '--dir','/agent','--dir','/work','--dir','/codex',
           '--ro-bind',str(AUTH),'/codex/auth.json',
           '--ro-bind',str(Path(input_dir).resolve()),'/input',
           '--bind',str(Path(output_dir).resolve()),'/output',
           '--setenv','HOME','/agent','--setenv','CODEX_HOME','/codex',
           '--setenv','PATH','/usr/bin:/bin:/app','--setenv','LANG','C.UTF-8',
           '--chdir','/work','--',*command]
    return args

def preflight(input_dir,output_dir):
    code='''import pathlib,json
hidden=['/mnt/data/yjh/RoboTwin','/mnt/data/yjh/astra-vla','/mnt/data/yjh/dataset',
        '/home/aaa/.codex/sessions','/home/aaa/.codex/config.toml','/home/aaa/.codex/skills',
        '/root','/proc/1/root/mnt/data/yjh/RoboTwin']
report={'blocked':{p:not pathlib.Path(p).exists() for p in hidden},
        'input_files':sorted(p.name for p in pathlib.Path('/input').iterdir()),
        'workspace_files':list(pathlib.Path('/work').iterdir()),
        'codex_home_files':sorted(p.name for p in pathlib.Path('/codex').iterdir()),
        'visible_processes':len(list(pathlib.Path('/proc').glob('[0-9]*')))}
assert all(report['blocked'].values())
assert report['codex_home_files']==['auth.json'] and report['workspace_files']==[]
print(json.dumps(report))
'''
    p=subprocess.run(sandbox(input_dir,output_dir,['/usr/bin/python3','-c',code],False),capture_output=True,text=True)
    if p.returncode:raise RuntimeError('Isolation preflight failed: '+p.stderr)
    report=json.loads(p.stdout);report['passed']=True
    return report

def model_command(input_dir,output_dir,images):
    args=['/app/codex','exec','--ignore-user-config','--ignore-rules','--ephemeral',
          '--skip-git-repo-check','--sandbox','read-only','--model','gpt-6-astra',
          '--json','--color','never','-c','model_reasoning_effort="max"',
          '-c','approval_policy="never"','-c','web_search="disabled"',
          '-c','project_doc_max_bytes=0','-c','model_instructions_file="/input/instructions.md"',
          '-c','mcp_servers={}','-c','suppress_unstable_features_warning=true',
          '--disable','shell_tool','--disable','unified_exec','--disable','multi_agent',
          '--disable','plugins','--disable','skill_search','--disable','memories',
          '--disable','code_mode_host',
          '--enable','skip_host_skill_discovery',
          '--output-schema','/input/decision.schema.json',
          '--output-last-message','/output/decision.json','-C','/work']
    for name in images:args+=['--image','/input/'+name]
    args+=['-']
    return sandbox(input_dir,output_dir,['/usr/bin/strace','-f','-qq','-e','trace=%file',
          '-o','/output/file-access.log',*args])

def audit_output(output_dir):
    output=Path(output_dir)
    events=[json.loads(x) for x in (output/'events.jsonl').read_text().splitlines() if x.strip()]
    # The CLI emits this exact startup diagnostic when code execution is disabled.
    # Exempt it only before turn.started; every other non-text item fails closed.
    disabled_code_mode='Code Mode is unavailable because code-mode host is disabled. Code mode will fail closed; enable `features.code_mode_host` and install `codex-code-mode-host`.'
    tools=[];startup_diagnostics=[];turn_started=False
    for event in events:
        if event.get('type')=='turn.started':turn_started=True
        item=event.get('item')
        if not item or item.get('type') in {'agent_message','reasoning'}:continue
        if not turn_started and item.get('type')=='error' and item.get('message')==disabled_code_mode:
            startup_diagnostics.append(disabled_code_mode);continue
        tools.append(event)
    if tools:raise RuntimeError('Model attempted a forbidden tool; do not execute decision')
    trace=(output/'file-access.log').read_text()
    # These paths are absent from the namespace; successful access is a fatal failure.
    suspicious=[line for line in trace.splitlines() if any(x in line for x in
        ['/mnt/data/yjh','/home/aaa','.hdf5','.zarr','stack_blocks_two.py','scene_state.py'])
        and 'ENOENT' not in line and 'EACCES' not in line]
    if suspicious:raise RuntimeError('File-access audit failed; decision blocked')
    return {'passed':True,'forbidden_tool_events':0,'forbidden_file_accesses':0,
            'startup_diagnostics':startup_diagnostics,
            'file_trace_sha256':hashlib.sha256(trace.encode()).hexdigest(),
            'event_count':len(events),'thread_ids':[x.get('thread_id') for x in events if x.get('type')=='thread.started']}
