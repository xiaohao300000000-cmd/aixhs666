# Worker 注册表

> 由主控会话维护。子会话只读。

| Worker | 任务 | 状态 | 分支 | Worktree | 开始时间 | 报告 | 备注 |
|---|---|---|---|---|---|---|---|
| W1 | T07 小红书搜索采集 | RUNNING | `task/T07-xhs-search-collection` | `../worktrees/T07` | 2026-07-02 00:41 CST | `orchestration/reports/T07.md` | 新独立执行对话：019f1e8c-d772-7991-bfbb-e7b13b2b0f20；旧对话 019f1c1a-2a11-7bc0-97d9-2cc17e09e75f 无代码产出；T08-T10 按依赖排队 |
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
