# Worker 注册表

> 由主控会话维护。子会话只读。

| Worker | 任务 | 状态 | 分支 | Worktree | 开始时间 | 报告 | 备注 |
|---|---|---|---|---|---|---|---|
| W1 | T03 任务状态机 | RUNNING | `task/T03-task-state-machine` | `../worktrees/T03` | 2026-07-01 05:09 CST | `orchestration/reports/T03.md` | 独立执行对话：019f1a5f-4880-7ad2-9c86-3905d6c3cee4 |
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
