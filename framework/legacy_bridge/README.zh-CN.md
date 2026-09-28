# RoboTwin 三视角、AI 控制与 DP 训练

服务器：`aaa@is5090`。全部新增内容位于 `/mnt/data/yjh`。

## 运行内容

- RoboTwin：`/mnt/data/yjh/RoboTwin`，环境：`/mnt/data/yjh/conda_envs/robotwin`。
- 实验：`/mnt/data/yjh/robotwin_experiments/dp_stack_blocks_two`。
- 接口：`/mnt/data/yjh/robotwin_bridge`，服务绑定 `127.0.0.1:8766`。
- 原始数据：`/mnt/data/yjh/RoboTwin/data/yjh_dp50_clean/stack_blocks_two/aloha_agilex`。
- 权重：`/mnt/data/yjh/RoboTwin/XPolicyLab/policy/DP/checkpoints/yjh_dp50_clean-stack_blocks_two-aloha_agilex-joint-0`。

DP 使用官方 XPolicyLab 实现，从零训练。50 条专家示范，45 条训练、5 条验证；主摄、左右腕三路 RGB 加 14 维双臂状态，输出关节动作。原图 320×240，编码器内部缩至 160×120。batch=16，seed=0，600 epochs，EMA；第 1、25、50…600 epoch 保存完整权重。归一化只拟合训练集。权重采用临时文件后原子替换，接口不会加载半写入文件。

这是固定叠方块任务的视觉运动策略，没有语言条件，不具备随意改写子任务的能力。600 epochs 是训练计划，训练进度看日志，不能将任务已启动等同于模型已训练好。

## 看画面与控制

本机建立 SSH 转发：

```bash
ssh -N -L 127.0.0.1:8766:127.0.0.1:8766 is5090
```

浏览器打开 `http://127.0.0.1:8766/`，输入服务器 `/mnt/data/yjh/robotwin_bridge/access.token` 的令牌。令牌文件权限为 600；不要把令牌放进公共文档或提交仓库。首次已在 Codex 内打开并连接。

页面同时展示主摄、左腕、右腕，提供接管、中断、DP、重置及短码控制。腕相机固定在各自机械臂上，初始姿态朝前，物体可能在画面边缘；机械臂运动后视野会变化。没有把主摄画面复制为腕视角。

仿真在动作之间暂停物理推进；有动作时按物理步推进。空闲时刷新渲染约 1 Hz，运动及推理等待中约 2.5 Hz，实际频率受 GPU 负载影响。每幅观测包含采集时间和帧龄；这不是硬实时控制系统。画面保留 RTX 5090 当前兼容设置的光线追踪噪声。

## 任意 AI 的接入方式

任意能执行 HTTP 工具或 Python 的 AI 都能接入。每个 AI 使用不同 `client_id`。观测可多人同时读取，动作只接受当前控制者。提供 HTTP/OpenAPI 和 `client.py`；尚未绑定云模型账号或自动调用任何付费模型。

| 路径 | 用途 |
|---|---|
| GET `/v1/observe?inline=true` | 同一批三视角 JPEG data URL、真实末端坐标、关节反馈、版本和时间戳 |
| GET `/v1/frame/head` | 主摄 JPEG；腕视角名为 `left_wrist`、`right_wrist` |
| POST `/v1/control/claim` | 获取控制；`takeover=true` 取消旧控制代数的动作 |
| POST `/v1/control/hold` | 当前控制者请求暂停并取消旧动作 |
| POST `/v1/commands` | 有界 EEF 短码、运行 DP 或重置 |
| GET `/v1/commands/{command_id}` | 查询完成、失败、未到达或已取消的回执 |
| GET `/v1/training` | 数据、训练状态、最新 loss、可用权重 |
| GET `/openapi.json` | 机器可读接口规范 |

所有 `/v1` 请求要求 `Authorization: Bearer <token>`。使用 `observe?inline=true` 获得同步三视角；分别请求 frame 端点可能跨越两个渲染周期。返回的 `left_joints/right_joints` 为实际关节角加最后一项夹爪目标，夹爪目标并非力或接触传感器读数。不向 AI 发布物体真值坐标或专家轨迹。

控制循环：claim → 等待 `applied_epoch == epoch` 且 `busy == false` → observe → 携带观测的 epoch/revision 下发动作 → 等待回执 → observe。过期观测、旧控制代数及非控制者请求均返回 409。相同 command_id 和相同内容只执行一次；command_id 携带不同内容会拒绝。该去重记录在服务进程内，服务重启后需重新 claim 和获取观测。

短码支持 `X±/Y±/Z±`（世界坐标），level 1/2/3 对应 5 mm/2 cm/5 cm，`OPEN/CLOSE` 对应夹爪张闭；每次最多 8 条。保持末端姿态，经过原生规划器执行。返回目标与实际位移；位置误差超过 8 mm 标记 `target_not_reached`。规划期间可请求取消，物理执行在下一控制检查点停止；服务分别记录请求代数和实际应用代数。

DP 每次最多执行 120 个关节动作，默认 12；每次推理产生动作片段，逐动作及逐物理步检查控制代数。推理在线程中运行，接管后其结果会被丢弃，不继续写关节目标。新 DP 请求如遇旧推理尚未结束会提示稍后重试。一次 DP 调用使用开始时选中的权重版本，回执记录该版本。

Python 示例（在服务器上）：

```python
import sys
sys.path.insert(0, '/mnt/data/yjh/robotwin_bridge')
from client import RoboTwinClient
c = RoboTwinClient('ai-A')
c.claim(takeover=True)
c.wait_hold()
obs = c.save_views('/mnt/data/yjh/robotwin_bridge/ai-A-observation')
# 将三张 JPEG 作为图像输入交给视觉模型，保留相机标签。
r = c.command(obs, 'eef', [{'arm':'left', 'code':'Z+', 'level':1}])
print(c.wait(r))
obs = c.observe(False)
r = c.command(obs, 'dp', max_actions=12)
# 需要接管时 c.hold()，随后 c.wait_hold() 再提交新动作。
print(c.wait(r))
```

在其他电脑上运行 client.py 时设置 `ROBOTWIN_TOKEN`，通过 SSH 转发的本机 URL 访问即可。控制权是调度约束；令牌拥有者有权接管，client_id 不是独立账号权限体系。

## 查看任务、重启服务

```bash
source /mnt/data/yjh/activate_robotwin.sh
cat /mnt/data/yjh/robotwin_experiments/dp_stack_blocks_two/pipeline.status
tail -n 3 /mnt/data/yjh/robotwin_experiments/dp_stack_blocks_two/training/logs.json.txt
cat /mnt/data/yjh/robotwin_experiments/dp_stack_blocks_two/training.pid
bash /mnt/data/yjh/robotwin_bridge/start.sh
```

训练和接口是独立后台进程，退出 SSH 后继续运行；服务器重启后需要重新启动。不要在现有训练仍运行时再次运行 `scripts/run_training.sh`；该入口面向新训练，不自动续训。停止训练可对 training.pid 指定的当前训练进程发送 TERM，保留已完成的检查点；当前 epoch 不会自动补存。

## 验证记录

`verification/results.json` 保存实际三视角、左右臂移动、过期观测、非控制者拒绝、重复指令去重、动作中接管与重置测试结果。`events.jsonl` 记录所有控制提交和回执。DP 验证另存 `verification/dp-results.json`，成功率需完成训练后在独立种子上评估。

2026-09-24 实测：50 条、16,692 帧数据的状态和动作均为有限数值；验证集 episode 为 13、15、24、29、39。已修复上游验证集始终只选最后一条的问题，旧试跑保留在实验目录 `pilot-validation-bug`，当前训练从修复后的划分重新开始。

左右臂 5 mm 移动、旧观测拒绝、非控制者拒绝、去重、接管和重置均通过。真实 DP 第 1 epoch 权重执行 2 个动作通过；DP 推理期间由另一客户端接管，0.105 秒确认停止且未执行旧推理结果。这是一次实测延迟，不代表最坏延迟保证。官方 WebSocket 调试客户端的已解码 RGB、JPEG RGB 两种输入都通过，每种测试 batch=10、1 episode、20 步。依赖检查和 Python/脚本语法检查通过。

训练 PID 和最新状态分别保存在实验目录 `training.pid`、`pipeline.status`；交接快照为 `status-at-handoff.json`，源码补丁为 `robotwin.patch`、`xpolicylab.patch`，环境版本为 `pip-freeze.txt`。
