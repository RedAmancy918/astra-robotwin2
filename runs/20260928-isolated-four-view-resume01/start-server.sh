#!/usr/bin/env bash
set -eo pipefail
source /mnt/data/yjh/activate_robotwin.sh
set -u
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4
export ROBOTWIN_BRIDGE_PORT=8775
exec python -u "$ASTRA_VLA_AGENT_RUN/server.py"
