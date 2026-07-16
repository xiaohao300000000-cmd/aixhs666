# Worker 注册表

> 由主控会话维护。子会话只读。

| Worker | 任务 | 状态 | 分支 | Worktree | 开始时间 | 报告 | 备注 |
|---|---|---|---|---|---|---|---|
| W1 | V19-04-H1 审核队列 continue 状态热修 | RUNNING | `codex/v19-04-h1-queue-actions` | `/Users/xiaohao30000/.codex/worktrees/be3c/aixhs666` | 2026-07-17 | `orchestration/reports/V19-04-H1.md` | 独立执行对话 `019f6bd1-cef7-7882-a798-9216947a82df`；V19-04 已发布，线上验收发现空/完成态按钮误禁用 |
| W2 | - | IDLE | - | - | - | - | 默认可用 |
| W3 | - | DISABLED | - | - | - | - | 稳定后启用 |
| W4 | - | DISABLED | - | - | - | - | 仅低冲突阶段启用 |

状态：

- IDLE
- ASSIGNED
- RUNNING
- WAITING_REVIEW
- REVISION
- BLOCKED
- DISABLED
