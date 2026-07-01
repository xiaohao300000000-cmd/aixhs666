# Worker 注册表

> 由主控会话维护。子会话只读。

| Worker | 任务 | 状态 | 分支 | Worktree | 开始时间 | 报告 | 备注 |
|---|---|---|---|---|---|---|---|
| W1 | T07 小红书搜索采集 | ASSIGNED | `task/T07-xhs-search-collection` | `../worktrees/T07` | 2026-07-01 13:12 CST | `orchestration/reports/T07.md` | 独立执行对话待创建；T08-T10 按依赖排队 |
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
