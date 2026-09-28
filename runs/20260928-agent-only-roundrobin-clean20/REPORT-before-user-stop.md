# 纯视觉 Agent：20 局轮转评估

状态：executing；第 7 轮；已开始 20/20 局。
成功 0；终止失败 0；未完成 20。

从原始初始位置开始；DP 初始动作 0 步；无 DP/VLA 调用或回退。
模型 gpt-6-astra / max，输入主摄与左右腕 RGB、机器人状态、执行回执和保存的记忆。
保持原 Agent 动作接口：XYZ 5/20/50 mm 位移和夹爪开合；保持当前末端姿态，不能主动旋转。
每局每轮执行一次 Agent 决策，最多 8 条末端指令；单次批量大小不是整局动作上限。
整局无时间、动作、重试或决策次数上限；未完成状态保存后继续轮转。
仅官方成功或方块落地结束一局；基础设施异常不计任务失败。
20 个正式种子 100000–100019；demo_clean；验证种子 999010/999011 不纳入。
物体真值仅用于保存/恢复和终止判定，不提供给 Agent。
物理恢复验证位置、速度、关节驱动、夹爪和 RNG；内部求解器缓存和渲染噪声不保证逐位一致。
视频直接标 AGENT 或 SYSTEM，并逐帧记录 command_id，便于对齐指令。

| seed | 状态 | 轮转访问 | 动作计数 | Agent 决策 |
|---|---|---:|---:|---:|
| 100000 | pending_next_round | 7 | 11 | 7 |
| 100001 | pending_next_round | 7 | 16 | 7 |
| 100002 | pending_next_round | 7 | 13 | 7 |
| 100003 | pending_next_round | 7 | 10 | 7 |
| 100004 | pending_next_round | 7 | 14 | 7 |
| 100005 | pending_next_round | 7 | 11 | 7 |
| 100006 | pending_next_round | 7 | 16 | 7 |
| 100007 | pending_next_round | 7 | 9 | 7 |
| 100008 | pending_next_round | 6 | 6 | 6 |
| 100009 | pending_next_round | 6 | 10 | 6 |
| 100010 | pending_next_round | 6 | 13 | 6 |
| 100011 | pending_next_round | 6 | 7 | 6 |
| 100012 | pending_next_round | 6 | 6 | 6 |
| 100013 | pending_next_round | 6 | 14 | 6 |
| 100014 | pending_next_round | 6 | 7 | 6 |
| 100015 | pending_next_round | 6 | 14 | 6 |
| 100016 | pending_next_round | 6 | 10 | 6 |
| 100017 | pending_next_round | 6 | 12 | 6 |
| 100018 | pending_next_round | 6 | 11 | 6 |
| 100019 | pending_next_round | 6 | 17 | 6 |

尚未完成的局不记为失败；全部终止后才计算最终 20 局成功率。
