@AGENTS.md

# Claude Code 项目入口

本仓库支持 Codex 与 Claude Code 交替接手。

## 每次会话开始

先读取：

1. `README.md`
2. `PROJECT_DASHBOARD.md`
3. `TASKS.md`
4. `HANDOFF.md`
5. `DECISIONS.md`

主控会话还必须读取：

- `docs/ORCHESTRATION.md`
- `docs/CONCURRENCY_POLICY.md`
- `orchestration/WORKER_REGISTRY.md`
- `orchestration/FILE_LOCKS.md`

## 角色选择

### 作为项目经理主控会话

读取并遵守：

- `CLAUDE_MASTER_PROMPT.md`
- `MASTER_CODEX_PROMPT.md`

以仓库文件为事实来源，不依赖之前的聊天记忆。

### 作为执行子会话

读取并遵守：

- `CLAUDE_WORKER_PROMPT.md`
- 主控指定的 `orchestration/briefs/TXX.md`

只能执行一个任务，不得修改全局进度文件。

## Claude Code 特别规则

- 不要把自动记忆当作项目事实来源
- 项目状态必须写入 Git 仓库
- 发现文档与代码冲突时，停止并交给主控裁决
- 使用 worktree 时，每个 Worker 只操作自己的工作区
- 完成任务后必须生成标准子任务报告
