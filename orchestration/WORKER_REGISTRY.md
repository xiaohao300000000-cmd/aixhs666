# Worker 注册表

> 由主控会话维护。子会话只读。

| Worker | 任务 | 状态 | 分支 | Worktree | 开始时间 | 报告 | 备注 |
|---|---|---|---|---|---|---|---|
| W1 | V19-02 Base CRM | RUNNING | `codex/v19-02-base-crm` | `/Users/xiaohao30000/.codex/worktrees/e671/aixhs666` | 2026-07-16 | `orchestration/reports/V19-02.md` | 独立执行对话 `019f6ab4-bf72-7af1-95eb-9edc8c44f9fa`；主控监督 |
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
