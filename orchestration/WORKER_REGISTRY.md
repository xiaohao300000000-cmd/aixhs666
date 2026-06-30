# Worker 注册表

> 由主控会话维护。子会话只读。

| Worker | 任务 | 状态 | 分支 | Worktree | 开始时间 | 报告 | 备注 |
|---|---|---|---|---|---|---|---|
| W1 | T05 去重与发现关系 | RUNNING | `task/T05-dedup-discovery-relations` | `../worktrees/T05` | 2026-07-01 05:38 CST | `orchestration/reports/T05.md` | 独立执行对话：019f1a79-85be-74f2-a583-bfdb7dfc4f48 |
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
