#!/usr/bin/env bash
set -euo pipefail
source /mnt/data/yjh/activate_robotwin.sh
bridge=/mnt/data/yjh/robotwin_bridge
if [[ -f "$bridge/server.pid" ]] && kill -0 "$(cat "$bridge/server.pid")" 2>/dev/null; then
  echo "Bridge is already running: $(cat "$bridge/server.pid")"; exit 0
fi
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4
nohup python -u "$bridge/server.py" > "$bridge/server.log" 2>&1 < /dev/null &
echo $! > "$bridge/server.pid"
echo "Bridge started: $(cat "$bridge/server.pid")"
