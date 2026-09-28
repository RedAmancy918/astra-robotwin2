# 运行说明

本仓库保存实际使用过的框架与实验快照，依赖已有 RoboTwin 环境。当前路径来自 is5090，不是无需外部资产的一键安装包。

## 原环境与依赖

- RoboTwin：`/mnt/data/yjh/RoboTwin`
- Python 环境：`/mnt/data/yjh/conda_envs/robotwin`
- 激活脚本：`/mnt/data/yjh/activate_robotwin.sh`
- 实验目录：`/mnt/data/yjh/astra-vla/runs/`
- 模型：现有 Codex 登录下的 `gpt-6-astra` / `max`
- 隔离：Linux bubblewrap、strace、用户与 PID 命名空间
- 渲染与录像：SAPIEN、FFmpeg

完整依赖见 `records/training-dp50/pip-freeze.txt`，上游提交、当前补丁与自定义配置见 `records/reproduction-export/`。应用补丁前核对提交。RoboTwin 修改包括中断钩子及渲染兼容；XPolicyLab 修改包括训练/验证划分、归一化、检查点保存及 CPU 加载。

## 当前入口

`framework/four_view_agent/` 是当前实现的便利副本；`runs/20260928-isolated-four-view-resume01/` 保存实际冻结版本。

- `server.py`：四路 RGB、EEF/夹爪命令、官方判定与录像。
- `runner.py`：Agent 闭环、输入白名单、执行回执及结果。
- `isolation.py`：文件/进程隔离与输出审计。
- `preflight.py`：无场景的隔离与模型连接预检。
- `camera_setup.py`：固定斜侧俯视 45° 相机。
- `scene_state.py`：模拟器状态保存/恢复，不提供给模型。
- `instructions.md` / `decision.schema.json`：模型说明与动作格式。
- `start-server.sh`：环境激活与服务启动。

模型输出 TCP 位姿 `[x,y,z,qw,qx,qy,qz]`、离散 XYZ 平移和夹爪开合。目标由视觉模型估计，关节轨迹由通用 IK/运动规划生成；当前没有精确的图像到物体三维坐标反投影模块。

## 准备新一轮运行

不要直接在归档 run 内启动或覆盖结果。创建新的空目录，复制相应框架实现，并准备以下仅模拟器可见的文件：

1. `private/source-scene.pkl`：停止快照。
2. `private/resume-source.json`：种子、快照哈希与前一阶段计数。
3. `private/agent-continuation.json`：仅同一模型本局自己的记忆和精简反馈。
4. 新的 `protocol.json`：源码及上述文件的 SHA-256、输入边界、成功判定与来源。

实际四视角 run 已归档上述结构。位置、速度和驱动状态有恢复校验；派生加速度缓存不保证逐位一致。

先在新目录运行 `preflight.py`，检查 `preflight/result.json`。凭据使用目标机器已有的 Codex 登录，仓库不携带登录文件。迁移时需调整 `isolation.py` 的 CLI 路径、`start-server.sh` 的环境路径，以及服务/驱动涉及的原机路径，然后为新运行生成协议；不要修改旧实验协议来冒充原运行。

服务的启动形式是设置 `ASTRA_VLA_AGENT_RUN` 为准备好的新目录，设置 `ASTRA_INITIAL_SEED` 为其模拟器侧恢复配置的种子，然后执行该目录的 `start-server.sh`；在另一个终端、相同 Python 环境中执行新目录的 `runner.py`。当前四视角端口为 8775，三视角隔离版为 8773。

任务无动作/时间上限。官方成功后追加 500 个物理步验证；`progress.json` 为进度，`result.json` 为自然结束结果，用户中断另存 `stop-summary.json`。

## 只读核验

```bash
python3 tools/verify_archive.py
```

核验四条视频的哈希、选定协议冻结文件、基础凭据模式与 Python 语法，不调用模型或仿真。
