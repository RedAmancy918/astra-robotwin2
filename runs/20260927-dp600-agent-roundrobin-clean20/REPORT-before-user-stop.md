# DP600 + 视觉 agent：20 局轮转评估

状态：agent_thinking；轮次 36；已有 20/20 局获得执行机会。
成功 0；失败 0；未完成 20。

每局每轮执行一次视觉 agent 决策，之后轮到下一局；整局没有时间、动作或决策次数上限。
初次进入新场景先执行 120 个 DP 动作，再进行该轮的一次视觉决策。
未完成场景保存进度后继续，不会因轮转被重置或计为失败。
首局从旧串行任务的 178 个动作、7 次已执行决策继续，仿真进程保持原状。
其余场景保存物理状态、驱动目标、夹爪状态、策略观测历史和随机数状态；每次恢复验证一致性。
不保证恢复后物理接触求解器的内部缓存或渲染噪声逐位一致；这是轮转协议的限制。
Seed 100000–100019；demo_clean；600.ckpt；gpt-6-astra / max；三视角 RGB 和机器人状态。
结束条件仍为官方成功或方块掉至地面；基础设施异常保留为未完成。
视频按场景分段录制并保留动作计数；首局视频仍在旧 run。

| seed | 状态 | 轮转访问 | 总动作 | agent 决策 |
|---|---|---:|---:|---:|
| 100000 | pending_next_round | 35 | 363 | 42 |
| 100001 | pending_next_round | 36 | 342 | 36 |
| 100002 | pending_next_round | 36 | 343 | 36 |
| 100003 | pending_next_round | 36 | 334 | 36 |
| 100004 | pending_next_round | 36 | 318 | 36 |
| 100005 | pending_next_round | 36 | 478 | 36 |
| 100006 | pending_next_round | 36 | 330 | 36 |
| 100007 | pending_next_round | 36 | 403 | 36 |
| 100008 | pending_next_round | 36 | 231 | 36 |
| 100009 | in_progress | 36 | 459 | 35 |
| 100010 | pending_next_round | 35 | 219 | 35 |
| 100011 | pending_next_round | 35 | 309 | 35 |
| 100012 | pending_next_round | 35 | 314 | 35 |
| 100013 | pending_next_round | 35 | 368 | 35 |
| 100014 | pending_next_round | 35 | 260 | 35 |
| 100015 | pending_next_round | 35 | 301 | 35 |
| 100016 | pending_next_round | 35 | 416 | 35 |
| 100017 | pending_next_round | 35 | 347 | 35 |
| 100018 | pending_next_round | 35 | 273 | 35 |
| 100019 | pending_next_round | 35 | 297 | 35 |

未完成场景存在时只报告成功/失败/未完成数量，不把部分完成的比例当作最终成功率。
