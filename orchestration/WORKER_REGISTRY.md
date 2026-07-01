# Worker 注册表

> 由主控会话维护。子会话只读。

| Worker | 任务 | 状态 | 分支 | Worktree | 开始时间 | 报告 | 备注 |
|---|---|---|---|---|---|---|---|
| W1 | T06 查询管理 API | RUNNING | `task/T06-query-management-api` | `../worktrees/T06` | 2026-07-01 12:58 CST | `orchestration/reports/T06.md` | 独立执行对话：019f1c0d-46a0-7f81-aa27-ffd46120ec90；T07-T10 按依赖排队 |
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
