#!/usr/bin/env bash
set -eo pipefail
source /mnt/data/yjh/activate_robotwin.sh
set -u
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4
export ROBOTWIN_BRIDGE_PORT=8768
export ASTRA_VLA_AGENT_RUN
python -u "$ASTRA_VLA_AGENT_RUN/server.py" > "$ASTRA_VLA_AGENT_RUN/server.log" 2>&1 &
simulation_pid=$!
echo "$simulation_pid" > "$ASTRA_VLA_AGENT_RUN/server.pid"
trap 'kill -TERM "$simulation_pid" 2>/dev/null || true' EXIT
python -u "$ASTRA_VLA_AGENT_RUN/runner.py" > "$ASTRA_VLA_AGENT_RUN/runner.log" 2>&1
