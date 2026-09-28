"""Summarize a completed checkpoint evaluation and its paired-scene baseline."""
from pathlib import Path
import json, sys, time, csv

project = Path(__file__).resolve().parents[1]
run = Path(sys.argv[1]).resolve()
manifest = json.loads((run / 'manifest.json').read_text())
baseline = project / 'runs' / manifest['comparison_run']

def load(folder):
    summary = json.loads((folder / 'summary.json').read_text())
    rows = [json.loads(line) for line in (folder / 'episodes.jsonl').read_text().splitlines()]
    counted = [row for row in rows if row['counted']]
    assert summary['status'] == 'complete'
    assert len(counted) == summary['completed'] == summary['planned'] == 20
    assert sum(row['success'] for row in counted) == summary['successes']
    assert len({row['seed'] for row in counted}) == len(counted)
    assert [row['seed'] for row in counted] == summary['evaluated_seeds']
    return summary, rows, {row['seed']: row for row in counted}

summary, rows, current = load(run)
old_summary, old_rows, old = load(baseline)
assert list(current) == list(old) == manifest['expected_paired_seeds'], 'Scene seeds do not match'
assert summary['checkpoint_epoch'] == 75 and old_summary['checkpoint_epoch'] == 600
runtime = json.loads((run / 'runtime.json').read_text())
old_runtime = json.loads((baseline / 'runtime.json').read_text())
assert runtime['source_sha256'] == old_runtime['source_sha256']
assert runtime['versions'] == old_runtime['versions']
low, high = summary['wilson_95_percent']
success = summary['successes']
paired = {'both_success': 0, 'epoch75_only_success': 0, 'epoch600_only_success': 0, 'both_fail': 0}
for seed in current:
    a, b = current[seed]['success'], old[seed]['success']
    key = 'both_success' if a and b else 'epoch75_only_success' if a else 'epoch600_only_success' if b else 'both_fail'
    paired[key] += 1
comparison = {
    'checked_at': time.strftime('%Y-%m-%d %H:%M:%S %z'), 'paired_scenes': len(current),
    'epoch75': {'successes': success, 'episodes': len(current), 'success_rate': summary['success_rate'], 'wilson_95_percent': [low, high]},
    'epoch600': {'successes': old_summary['successes'], 'episodes': len(old), 'success_rate': old_summary['success_rate'], 'wilson_95_percent': old_summary['wilson_95_percent']},
    'difference_percentage_points': 100 * (summary['success_rate'] - old_summary['success_rate']),
    'paired_results': paired, 'same_scene_order': True, 'same_model_and_evaluator_source': True,
    'scope': 'Paired development-set comparison, not an independent final-test estimate after checkpoint selection',
}
(run / 'comparison.json').write_text(json.dumps(comparison, ensure_ascii=False, indent=2) + '\n')
with (run / 'comparison.csv').open('w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=['seed', 'epoch75_success', 'epoch600_success', 'epoch75_actions', 'epoch600_actions', 'epoch75_reason'])
    writer.writeheader()
    for seed, row in current.items():
        writer.writerow({'seed': seed, 'epoch75_success': row['success'], 'epoch600_success': old[seed]['success'],
                         'epoch75_actions': row['actions'], 'epoch600_actions': old[seed]['actions'], 'epoch75_reason': row['reason']})

lines = [
    '# stack_blocks_two — 75.ckpt 与 600.ckpt 对照', '',
    f"完成核查：{comparison['checked_at']}", '',
    f'**75.ckpt 成功率：{success}/20 = {100 * summary["success_rate"]:.1f}%**。', '',
    '| 检查点 | 成功 / 场景数 | 成功率 | Wilson 95% 区间 |',
    '|---|---:|---:|---:|',
    f'| 75.ckpt | {success}/20 | {100 * summary["success_rate"]:.1f}% | {low:.1f}%–{high:.1f}% |',
    f'| 600.ckpt | {old_summary["successes"]}/20 | {100 * old_summary["success_rate"]:.1f}% | {old_summary["wilson_95_percent"][0]:.1f}%–{old_summary["wilson_95_percent"][1]:.1f}% |', '',
    f'观测到的差值：{comparison["difference_percentage_points"]:+.1f} 个百分点。该差值仅描述本次 20 个配对场景，不等同于总体提升的统计结论。', '',
    '## 评估条件', '',
    '- 纯 Diffusion Policy，使用 EMA；本次没有 Astra 或其他大模型参与控制。',
    '- 相同的 20 个 clean 场景：seed=100000–100019，顺序相同，均按官方专家可解性检查流程评估。',
    '- 三摄像头：主摄、左腕、右腕 RGB；另输入双臂关节状态，输出关节动作。',
    '- 每局最多 800 动作；每个动作后按官方流程更新观测历史，成功后提前结束。',
    '- 成功条件：绿块在红块上方 5 cm，XY 误差各小于 2.5 cm、Z 误差小于 1.2 cm，双夹爪打开。',
    '- 模型/评估代码哈希、软件版本均与 600.ckpt 实验一致。记录器仅参数化检查点和运行标签。',
    f'- 75.ckpt 有效场景中的运行错误：{sum(row["error"] is not None for row in current.values())} 局；零动作错误排除：{sum(not row["counted"] for row in rows)} 局。',
    f'- 专家检查未通过种子：{summary["expert_rejected_seeds"] or "无"}。',
    f'- 75.ckpt 评估耗时（含初始化与专家检查）：{summary["elapsed_s"] / 60:.1f} 分钟。', '',
    '## 逐场景对照', '',
    '| 种子 | 75.ckpt 成功 | 600.ckpt 成功 | 75 动作数 | 600 动作数 | 75 结束原因 |',
    '|---:|:---:|:---:|---:|---:|---|',
]
for seed, row in current.items():
    lines.append(f'| {seed} | {"是" if row["success"] else "否"} | {"是" if old[seed]["success"] else "否"} | {row["actions"]} | {old[seed]["actions"]} | {row["reason"]} |')
lines += [
    '', '## 解释与边界', '',
    '75.ckpt 是已保存检查点中记录的验证 loss 最低者。该 loss 来自 online model，部署使用 EMA；不能预先把 loss 优势等同于任务成功率优势。', '',
    '本次是在查看最终权重表现后进行的检查点对照。这 20 个场景现在用于开发比较；后续若据此选择模型，最终成功率需用新的独立种子评估。', '',
    '600.ckpt 的训练 seed=0 单局诊断不计入此处任何分母，也没有作为 75.ckpt 的诊断结果。', '',
    '## 记录与复现', '',
    f'- 本次运行：`{run}`。',
    f'- 对照运行：`{baseline}`。',
    f'- 75.ckpt：`{manifest["checkpoint"]}`。',
    f'- SHA256：`{manifest["checkpoint_sha256"]}`。',
    '- `manifest.json`、`runtime.json`、`configs/`、源码快照：配置、版本、预先指定种子及检查点。',
    '- `episodes.jsonl` / `episodes.csv`、`summary.json`：逐局判定与统计。',
    '- `comparison.json` / `comparison.csv`：与 600.ckpt 的配对结果。',
    '- `expert-checks.jsonl`、`evaluation.log`、`policy-server.log`：原始检查与运行日志。',
    '- `videos/episode0.mp4` 起为逐局主摄视频；`final-frames.jpg` 为末帧汇总。',
    '- `video-validation.json`：每个视频的帧数与末帧解码检查。', '',
    '复现时使用新的空目录，例如：', '',
    '```bash', 'ASTRA_VLA_TEST_NUM=20 ASTRA_VLA_SEED_INDEX=0 \\',
    '  bash /mnt/data/yjh/astra-vla/scripts/run_eval.sh /mnt/data/yjh/astra-vla/runs/<新的运行名> 75',
    '```',
]
(run / 'REPORT.md').write_text('\n'.join(lines) + '\n')
log = project / 'EXPERIMENTS.md'
text = log.read_text()
marker = '状态：运行中。结果保存在该 run 的 summary.json、episodes.jsonl 与视频中。'
replacement = f'状态：已完成。75.ckpt 成功 **{success}/20 = {summary["success_rate"]:.1%}**，对照 600.ckpt 为 {old_summary["successes"]}/20；Wilson 95% 区间 {low:.1f}%–{high:.1f}%。完整对照见 `runs/{run.name}/REPORT.md`。'
assert marker in text
log.write_text(text.replace(marker, replacement, 1))
print(json.dumps(comparison, ensure_ascii=False, indent=2))
