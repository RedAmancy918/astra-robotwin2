# Astra RoboTwin 2

RoboTwin 双臂方块堆叠实验框架：Diffusion Policy 基线、视觉 Agent 接管、隔离运行的 EEF 控制与四视角 RGB 闭环。任务是把绿色方块放到红色方块上并松开夹爪。

## 当前结果

**四视角 Agent 在原场景续跑中成功堆叠**：新增 10 次决策、12 次动作，实际耗时 832.42 秒；官方成功判定后，额外 500 个物理步（2 秒）均保持成功。本阶段 0 DP、无人工补动作，10 次已完成调用的隔离审计全部通过。

这不是全新测试局。此前三视角阶段已有 72 次决策、115 次动作，整个场景累计 82 次决策、127 次动作。一次续跑成功不能解释为总体成功率，也不能单独证明第四相机的普遍提升幅度。

[结果报告](runs/20260928-isolated-four-view-resume01/RESULT_REPORT.md) · [原始判定](runs/20260928-isolated-four-view-resume01/result.json) · [最终审计](runs/20260928-isolated-four-view-resume01/completion-audit.json) · [实验记录](EXPERIMENTS.md)

| 实验 | 结果 | 解释边界 |
| --- | --- | --- |
| DP600，20 个未见 clean 场景 | 0/20 成功，800 动作上限 | 固定任务 DP，不是语言条件 VLA |
| DP75 对照 | 0/2 成功后用户停止 | 不是完整 20 局结果 |
| DP600 + Agent 轮转 | 0 成功、20 局中断 | 未完成局不能当作终止失败 |
| 纯 Agent 三视角轮转 | 0 成功、20 局中断 | 早期平移接口 |
| 隔离三视角单局 | 72 次决策后用户停止 | 0 成功、1 局中断 |
| 隔离四视角续跑 | 10 次新决策后成功 | 同一停止场景继续，额外 500/500 步稳定 |

早期 `agent-focused-seed100000` 与其连续录像曾受到专家源码接触影响，属于工程演示/命令重放，**不作为严格无泄漏独立评测**。对应 `LEAKAGE_AUDIT.md` 及更正说明完整保留。

## 四条代表录像

整个仓库只包含以下 **4 个 MP4 文件**，约 46 MB。其余录像保留在实验服务器，历史报告中的其他视频路径在本仓库可能没有对应文件。

| 录像 | 内容 |
| --- | --- |
| [DP600 未见场景失败](runs/20260927-dp600-stack-blocks-two-clean20/videos/episode0.mp4) | seed 100000，纯 DP 基线 |
| [DP600 + Agent 单局控制来源标注](runs/20260927-dp600-agent-roundrobin-clean20/exports/20260928-control-annotated/seed100000-control-annotated.mp4) | 区分 DP、Agent 与系统操作 |
| [隔离三视角 Agent 停止前录像](runs/20260928-isolated-visual-eval01/videos/agent-seed4885058-0.mp4) | 72 次决策、115 次动作后的中断 |
| [隔离四视角 Agent 成功录像](runs/20260928-isolated-four-view-resume01/videos/agent-seed4885058-0.mp4) | 新增 10 次决策、12 次动作并验证成功 |

四视角视频长 8.6 秒，按仿真物理时间录制；模型思考时仿真暂停。含等待的实际运行时间为 13 分 52 秒。视频与原文件逐字节一致，来源和哈希见 [media/manifest.json](media/manifest.json)。

## 框架与记录

| 路径 | 内容 |
| --- | --- |
| [framework/four_view_agent/](framework/four_view_agent/) | 当前四视角 EEF 服务、Agent 驱动、隔离执行与相机配置 |
| [framework/isolated_three_view_agent/](framework/isolated_three_view_agent/) | 上一阶段的三视角隔离控制器 |
| [framework/four_camera_preview/](framework/four_camera_preview/) | 从停止快照恢复并渲染第四视角 |
| [framework/legacy_bridge/](framework/legacy_bridge/) | 历史三摄像头/策略接管接口 |
| [runs/](runs/) | 12 个实验目录的代码快照、协议、模型输入/输出、执行回执和审计 |
| [records/training-dp50/](records/training-dp50/) | 训练配置、指标、种子和环境依赖 |
| [records/reproduction-export/](records/reproduction-export/) | RoboTwin/XPolicyLab 的版本、补丁与自定义配置 |
| [configs/](configs/) / [scripts/](scripts/) | 基线评测配置、状态与报告工具 |

Agent 接收主摄、左右腕及固定斜侧俯视 45° 的 RGB，还有机器人自身状态；输出绝对 TCP 位姿、XYZ 相对位移和夹爪开合，由通用 IK/运动规划执行。模型没有直接获得物体真值、深度、相机标定或专家策略。

## 使用与核验

```bash
git clone https://github.com/RedAmancy918/astra-robotwin2.git
cd astra-robotwin2
python3 tools/verify_archive.py
```

核验只读取归档，不启动模型或仿真。代码保留实验机 is5090 的路径约定，迁移运行见 [运行说明](docs/RUNNING.md)。训练数据、权重和大型仿真资产依赖外部安装，不在本仓库中。

运行时隔离验证的是模型输入/访问边界，不能审计基础模型预训练数据。`runs/**/private/` 中保留的是仅供模拟器使用的场景信息及本局记忆，不挂载给决策模型；它们不是登录凭据。令牌、账户登录文件和私钥均已排除，详见 [归档范围](docs/ARCHIVE_SCOPE.md)。
