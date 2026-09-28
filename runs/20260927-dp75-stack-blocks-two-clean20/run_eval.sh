#!/usr/bin/env bash
set -eo pipefail
export ASTRA_VLA_RUN="${1:?Run directory required}"
export ASTRA_VLA_CHECKPOINT="${2:-600}"
[[ "$ASTRA_VLA_RUN" = /* ]] || { echo 'Run directory must be absolute' >&2; exit 2; }
[[ "$ASTRA_VLA_CHECKPOINT" =~ ^[1-9][0-9]*$ ]] || { echo 'Checkpoint must be a positive epoch number' >&2; exit 2; }
mkdir -p "$ASTRA_VLA_RUN"
for record in evaluation.log episodes.jsonl summary.json progress.json; do
  [[ ! -e "$ASTRA_VLA_RUN/$record" ]] || { echo "Existing evaluation record: $record; use a new run directory" >&2; exit 2; }
done
cp /mnt/data/yjh/astra-vla/scripts/eval_recorded.py "$ASTRA_VLA_RUN/eval_recorded.py"
if [[ "$0" != "$ASTRA_VLA_RUN/run_eval.sh" ]]; then
  cp "$0" "$ASTRA_VLA_RUN/run_eval.sh"
fi
source /mnt/data/yjh/activate_robotwin.sh
set -u
export OMP_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4 MKL_NUM_THREADS=4
root=/mnt/data/yjh/RoboTwin/XPolicyLab
export ASTRA_VLA_POLICY_PORT
ASTRA_VLA_POLICY_PORT=$(bash "$root/utils/get_free_port.sh")
python -u "$root/setup_policy_server.py" --config_path "$root/policy/DP/deploy.yml" --overrides \
  port="$ASTRA_VLA_POLICY_PORT" host=127.0.0.1 bench_name=yjh_dp50_clean task_name=stack_blocks_two \
  ckpt_name=stack_blocks_two env_cfg_type=aloha_agilex seed=0 policy_name=DP action_type=joint checkpoint_num="$ASTRA_VLA_CHECKPOINT" \
  > "$ASTRA_VLA_RUN/policy-server.log" 2>&1 &
server_pid=$!
echo "$server_pid" > "$ASTRA_VLA_RUN/policy-server.pid"
trap 'kill "$server_pid" 2>/dev/null || true' EXIT
bash "$root/utils/wait_for_policy_server.sh" 127.0.0.1 "$ASTRA_VLA_POLICY_PORT" "$server_pid" "DP${ASTRA_VLA_CHECKPOINT} evaluation" 120
python -u "$ASTRA_VLA_RUN/eval_recorded.py" > "$ASTRA_VLA_RUN/evaluation.log" 2>&1
