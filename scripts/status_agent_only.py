from pathlib import Path
import runpy
r=Path('/mnt/data/yjh/astra-vla')
name=(r/'runs/latest-agent-only.txt').read_text().strip()
runpy.run_path(str(r/'runs'/name/'status.py'),run_name='__main__')
