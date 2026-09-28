#!/usr/bin/env bash
set -eo pipefail
source /mnt/data/yjh/activate_robotwin.sh
set -u
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4
export ASTRA_VLA_RUN="${1:?Run directory required}"
root=/mnt/data/yjh/RoboTwin/XPolicyLab
export ASTRA_VLA_POLICY_PORT
ASTRA_VLA_POLICY_PORT=$(bash "$root/utils/get_free_port.sh")
python -u "$root/setup_policy_server.py" --config_path "$root/policy/DP/deploy.yml" --overrides \
  port="$ASTRA_VLA_POLICY_PORT" host=127.0.0.1 bench_name=yjh_dp50_clean task_name=stack_blocks_two \
  ckpt_name=stack_blocks_two env_cfg_type=aloha_agilex seed=0 policy_name=DP action_type=joint checkpoint_num=600 \
  > "$ASTRA_VLA_RUN/policy-server.log" 2>&1 &
server_pid=$!
echo "$server_pid" > "$ASTRA_VLA_RUN/policy-server.pid"
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
bash "$root/utils/wait_for_policy_server.sh" 127.0.0.1 "$ASTRA_VLA_POLICY_PORT" "$server_pid" 'DP600 evaluation' 120
python -u /mnt/data/yjh/astra-vla/scripts/eval_recorded.py > "$ASTRA_VLA_RUN/evaluation.log" 2>&1
