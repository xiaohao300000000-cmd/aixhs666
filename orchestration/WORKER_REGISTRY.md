# Worker 注册表

> 由主控会话维护。子会话只读。

| Worker | 任务 | 状态 | 分支 | Worktree | 开始时间 | 报告 | 备注 |
|---|---|---|---|---|---|---|---|
| W1 | T05 去重与发现关系 | BLOCKED | `task/T05-dedup-discovery-relations` | `../worktrees/T05` | 2026-07-01 05:38 CST | `orchestration/reports/T05.md` | 线程 019f1a79-85be-74f2-a583-bfdb7dfc4f48、019f1a7b-24d9-7851-aaf2-5b2669efef94、019f1a7e-416a-7b42-893d-9b54aac4b820 均系统错误；worktree pending `local:b20b5051-b4f8-4c21-8567-4dcc25080ec8` 未出现 |
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
