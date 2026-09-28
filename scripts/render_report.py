"""Render a completed evaluation into a readable, evidence-linked experiment record."""
from pathlib import Path
import json,sys,time
project=Path(__file__).resolve().parents[1]
run=Path(sys.argv[1]).resolve()
summary=json.loads((run/'summary.json').read_text())
manifest=json.loads((run/'manifest.json').read_text())
episodes=[json.loads(line) for line in (run/'episodes.jsonl').read_text().splitlines()]
counted=[r for r in episodes if r['counted']]
assert summary['status']=='complete' and len(counted)==summary['planned']==20
success=sum(r['success'] for r in counted)
assert success==summary['successes']
excluded=[r for r in episodes if not r['counted']]
errors=[r for r in counted if r['error'] is not None]
low,high=summary['wilson_95_percent']
lines=[
    '# stack_blocks_two — DP 最终权重基线评估',
    '',f"完成核查：{time.strftime('%Y-%m-%d %H:%M:%S %z')}",
    '',f'**成功率：{success}/{len(counted)} = {100*success/len(counted):.1f}%**。',
    f'二项比例 Wilson 95% 区间：{low:.1f}%–{high:.1f}%。样本量为 20，此区间描述本次有限场景样本的不确定性。',
    '', '## 评估条件', '',
    '- 方法：纯 Diffusion Policy；没有 Astra 或其他大模型参与控制。',
    '- 权重：固定最终 600.ckpt，采用保存配置中的 EMA；没有根据测试成绩选择检查点。',
    '- 输入：主摄、左腕、右腕 RGB 和双臂关节状态；输出关节动作。',
    '- 场景：官方 demo_clean；从 seed=100000 开始，取 20 个通过专家可解性检查的场景。',
    '- 每局最多 800 个动作，任务成功后提前结束；每个动作后按官方流程更新观测历史。',
    '- 官方成功条件：绿块位于红块之上，XY 误差分别小于 2.5 cm、Z 误差小于 1.2 cm，双夹爪打开。',
    f"- 专家检查未通过的种子：{summary['expert_rejected_seeds'] or '无'}。零动作错误排除：{len(excluded)} 局。", 
    f'- 有效评估中的运行错误：{len(errors)} 局。',
    f"- 有效评估种子：{summary['evaluated_seeds']}。",
    f"- 评估耗时（含场景初始化与专家检查）：{summary['elapsed_s']/60:.1f} 分钟。",
    '', '## 逐局结果', '',
    '| 局 | 种子 | 成功 | 动作数 | 策略运行秒数 | 判定 |',
    '|---:|---:|:---:|---:|---:|---|',
]
for i,r in enumerate(counted,1):
    lines.append(f"| {i} | {r['seed']} | {'是' if r['success'] else '否'} | {r['actions']} | {r['wall_time_s']:.1f} | {r['reason']} |")
diagnostic_run=project/'runs/20260927-dp600-seen-seed0-diagnostic'
diagnostic_path=diagnostic_run/'summary.json'
if diagnostic_path.exists():
    diagnostic=json.loads(diagnostic_path.read_text())
    d=diagnostic['last_episode']
    assert diagnostic['status']=='complete' and diagnostic['completed']==1 and d['seed']==0
    lines += [
        '', '## 独立诊断：训练中见过的场景', '',
        f"同一份 600.ckpt 在训练 seed=0 的单局诊断中{'成功' if d['success'] else '失败'}，执行 {d['actions']} 个动作。该局不计入上面的 20 个未见场景。",
        f'- 诊断目录：`{diagnostic_run}`。',
        '- 单个训练场景的结果不能作为训练集整体成功率。',
    ]
training_path=project/'records/training-dp50/diagnostics.json'
if training_path.exists():
    training=json.loads(training_path.read_text())
    best=training['lowest_logged_validation_loss_among_saved_checkpoints']
    lines += [
        '', '## 训练曲线与下一步', '',
        f"最终第 600 轮 train loss 为 {training['final_train_loss']:.8f}，val loss 为 {training['final_validation_loss']:.8f}。在已保存检查点中，第 {best['epoch']} 轮记录的 val loss 最低，为 {best['validation_loss']:.8f}。",
        '训练 loss 继续下降而验证 loss 回升，说明存在过拟合迹象。结合训练种子诊断，需要重点检查未见场景泛化能力。此证据不足以排除其他失败原因。',
        '验证 loss 由 online model 计算，部署使用 EMA，不能据此直接断言早期检查点的成功率更高。下一步可将 75.ckpt 作为单独候选进行比较；这 20 个场景一旦用于选择检查点，应作为开发集，最终结果还需独立测试种子。',
    ]
lines += [
    '', '## 核查与限制', '',
    '- 所有结果由仿真任务判定记录，视频供核查使用。',
    '- 已抽查训练 episode 0 的第 0、100、323 帧：主摄、左腕、右腕在 HDF5、训练 Zarr 与部署适配器之间一致，状态和动作向量也一致。检查记录见 `records/training-dp50/input-consistency.json`。这不是全部数据或实时仿真链路的穷尽检查。',
    '- 该结果只属于上述纯 DP、检查点和 clean 场景设置；不能作为 Astra+DP 的成功率。',
    '- 本次没有评估随机背景、随机光照等域随机化，也没有开展检查点筛选。',
    '', '## 文件与复现', '',
    f'- 远端项目：`{project}`。',f'- 本次运行：`{run}`。',
    f"- 权重：`{manifest['checkpoint']}`。",f"- 权重 SHA256：`{manifest['checkpoint_sha256']}`。",
    '- `manifest.json`、`runtime.json`：参数、源码哈希、依赖与硬件。',
    '- `episodes.jsonl` / `episodes.csv`：逐局原始记录；`summary.json`：统计结果。',
    '- `expert-checks.jsonl`：专家可解性检查；`evaluation.log`、`policy-server.log`：完整日志。',
    '- `videos/episode0.mp4` 起为逐局主摄视频，文件编号与 episode_index 一致。',
    '- `final-frames.jpg`：全部有效评估视频的末帧汇总；`video-validation.json`：视频帧数与末帧解码检查。',
    '- `records/training-dp50/epoch-metrics.csv`、`loss.png`：600 轮训练曲线。',
]
(run/'REPORT.md').write_text('\n'.join(lines)+'\n')
log=project/'EXPERIMENTS.md'
text=log.read_text()
text=text.replace('状态：准备运行。结果以对应 runs 目录的 summary.json 和 episodes.jsonl 为准。',
    f'状态：已完成。成功率 **{success}/20 = {success/20:.1%}**，Wilson 95% 区间 {low:.1f}%–{high:.1f}%。详细结果见 `runs/{run.name}/REPORT.md`；原始记录见该目录的 summary.json 和 episodes.jsonl。')
log.write_text(text)
print(run/'REPORT.md')
