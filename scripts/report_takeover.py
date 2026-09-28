"""Record the outcome of one completed, interactive agent takeover pilot."""
from pathlib import Path
import json, time, sys, hashlib

run = Path(sys.argv[1]).resolve()
project = run.parents[1]
handoff = json.loads((run / 'handoff.json').read_text())
resume = json.loads((run / 'resume.json').read_text())
recovery = json.loads((run / 'recovery-progress.json').read_text())
final = json.loads((run / 'recovery-final-observation.json').read_text())
assert recovery['status'] == 'complete'
assert recovery['task_success'] == final['snapshot']['task_success']
events = [json.loads(line) for line in (run / 'events.jsonl').read_text().splitlines()]
commands = {e['command']['command_id']: e['command'] for e in events if e['event'] == 'command_submitted'}
receipts = [e['receipt'] for e in events if e['event'] == 'command_finished']
dp_actions = sum(r.get('actions_executed', 0) for r in receipts if commands[r['command_id']]['kind'] == 'dp')
eef = [r for r in receipts if commands[r['command_id']]['kind'] == 'eef']
steps = [step for r in eef for step in r.get('steps', [])]
misses = [r for r in eef if r['status'] == 'target_not_reached']
assert dp_actions + len(steps) == final['snapshot']['action_count']
assert handoff['busy_before_claim'] and handoff['old_receipt']['status'] == 'cancelled'
assert resume['receipt']['status'] == 'completed' and resume['receipt']['actions_executed'] == 12
assert all(r.get('checkpoint', '').endswith('/600.ckpt') for r in receipts if commands[r['command_id']]['kind'] == 'dp')
success = bool(recovery['task_success'])
result = {
    'status': 'complete', 'pilot_type': 'single-scene interactive vision-agent takeover',
    'completed_at': time.strftime('%Y-%m-%d %H:%M:%S %z'), 'seed': 100000, 'checkpoint_epoch': 600,
    'task_success': success, 'dp_to_agent_handoff_s': handoff['takeover_applied_s'],
    'agent_to_dp_handoff_s': resume['handoff_applied_s'], 'old_policy_command_cancelled': True,
    'dp_actions_before_agent': handoff['after_actions'], 'total_dp_actions': dp_actions,
    'agent_eef_steps_attempted': len(steps), 'agent_command_batches': len(eef),
    'target_not_reached_batches': len(misses), 'total_task_action_calls': final['snapshot']['action_count'],
    'visual_findings': ['First grasp attempt missed the green block.',
                        'After a lower grasp, the green block visibly followed the right gripper during lift and lateral transport.',
                        'Several fixed-orientation EEF commands did not reach their requested positions.'],
    'object_ground_truth_or_expert_actions_used_by_agent': False,
    'scope': 'One selected known-failure scene; includes additional manual EEF actions; not an aggregate success-rate estimate.',
    'source_sha256': hashlib.sha256((run / 'server.py').read_bytes()).hexdigest(),
}
(run / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
outcome = '通过官方任务成功判定' if success else '未通过官方任务成功判定'
lines = [
    '# 600.ckpt + 视觉 agent 接管：单场景可行性测试', '',
    f"记录时间：{result['completed_at']}", '',
    f'**最终结果：{outcome}。** 本次只有 seed=100000 一局，不作为总体成功率。', '',
    '## 实际执行', '',
    f'1. 固定 600.ckpt 执行 {handoff["after_actions"]} 个关节动作。',
    f'2. DP 正在执行时，视觉 agent 请求接管；旧命令被取消，{handoff["takeover_applied_s"]:.3f} 秒后确认生效。',
    f'3. Agent 根据主摄、左腕、右腕 RGB 和机器人自身状态，执行 {len(steps)} 个末端短码动作尝试，共 {len(eef)} 批。',
    '4. 第一次抓取没有带起绿块；降低抓取位置后，绿块随右手抬升并横移。',
    f'5. {len(misses)} 批固定姿态平移动作出现目标未到达，接口返回实际位移与位置误差。',
    f'6. 控制交回 600.ckpt，先验证 12 个动作，再继续剩余预算；整局共 {dp_actions} 个 DP 动作，加 {len(steps)} 个 agent 末端动作。', '',
    '## 能说明什么', '',
    '- 执行中的接管、旧动作取消、重新观测、末端纠偏和交回 DP 均已实际运行。',
    '- 画面显示 agent 改善了抓取和局部搬运，这不自动等同于整局任务成功。',
    f'- 本轮最终{outcome}；以仿真任务状态为准。',
    '- 目标未到达的原因还需区分构型可达性、规划失败和位置跟踪误差，不能仅凭回执断言机械臂物理上不可达。',
    '- 目前 agent 的动作接口只支持世界坐标平移和夹爪开闭，保持当前末端朝向。进一步测试应加入有界姿态调整和更完整的规划/执行状态，再评估双手配合。', '',
    '## 评估边界', '',
    '- 使用与官方 DP600 失败案例相同的 seed=100000、demo_clean 场景。',
    '- Agent 为本次对话中的视觉决策控制，通过工具读取三视角并发出指令；没有调用付费外部模型服务。',
    '- 没有向 agent 提供方块真值坐标或专家动作，决策依据保存在观测图片和指令理由中。',
    '- 这是交互式单场景试验，有额外末端动作和控制暂停，不能直接与纯 DP 的 20 局成功率作公平总体比较。',
    '- 接管延迟为这次运行的观测值，不是最坏延迟保证。', '',
    '## 文件', '',
    '- `videos/agent-seed100000-0.mp4`：三视角动作视频。按动作期间采样，以 5 fps 播放；省略空闲等待，不表示真实仿真时间。',
    '- `video-frames.jsonl`：视频帧对应的墙钟时间、动作阶段和动作计数。',
    '- `observations/`：每次视觉决策的同步三视角与机器人状态。',
    '- `agent-requests.jsonl`、`events.jsonl`：指令、理由、控制权与回执。',
    '- `handoff.json`、`resume.json`：两个方向的控制交接。',
    '- `recovery-rollout.jsonl`、`recovery-final-observation.json`：交回 DP 后的执行与最终判定。',
    '- `manifest.json`、`server.py`、`summary.json`：配置、控制器快照与汇总。',
]
(run / 'REPORT.md').write_text('\n'.join(lines) + '\n')
log = project / 'EXPERIMENTS.md'
with log.open('a') as f:
    f.write(f'\n## 2026-09-27 — 600.ckpt + 视觉 agent 接管\n\nRun: `{run.name}`。已完成 seed=100000 单局可行性试验：运行中的接管约 {handoff["takeover_applied_s"]:.3f} 秒生效，补上绿块抓取并完成一段搬运；{len(misses)} 批末端平移动作未到达目标。交回 600.ckpt 后继续，总计 {dp_actions} 个 DP 动作和 {len(steps)} 个末端动作尝试，最终{outcome}。不是总体成功率评估，详细视频、回执和限制见该 run 的 REPORT.md。\n')
print(json.dumps(result, ensure_ascii=False, indent=2))
