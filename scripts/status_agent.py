from pathlib import Path
import runpy
project = Path(__file__).resolve().parents[1]
run = (project / 'runs/latest-agent-unlimited.txt').read_text().strip()
runpy.run_path(str(project / 'runs' / run / 'status.py'), run_name='__main__')
