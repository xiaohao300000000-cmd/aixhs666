# Codex 与 Claude Code 交接规则

## 1. 交接原则

Codex 和 Claude Code 都可以接手项目。

项目的正式记忆来自：

- Git 提交
- `TASKS.md`
- `PROJECT_DASHBOARD.md`
- `HANDOFF.md`
- `DECISIONS.md`
- 任务简报
- 子任务报告

聊天上下文和工具自己的自动记忆只能作为辅助，不能作为事实来源。

## 2. Codex 接手

入口：

- 主控：`MASTER_CODEX_PROMPT.md`
- Worker：`WORKER_CODEX_PROMPT.md`
- 通用规则：`AGENTS.md`

## 3. Claude Code 接手

入口：

- 持久项目说明：`CLAUDE.md`
- 主控：`CLAUDE_MASTER_PROMPT.md`
- Worker：`CLAUDE_WORKER_PROMPT.md`

`CLAUDE.md` 会导入 `AGENTS.md`，两种工具共享同一套项目规则。

## 4. 工具切换前的必要动作

离开的主控必须：

1. 提交或清理当前工作区
2. 更新 `HANDOFF.md`
3. 更新 `PROJECT_DASHBOARD.md`
4. 更新 Worker 注册表
5. 标明所有活跃分支
6. 标明待验收报告
7. 标明阻塞和未解决决策
8. 推送到 GitHub

## 5. 新工具接手检查

新的项目经理必须检查：

```bash
git status
git branch --all
git log --oneline -10
git worktree list
```

然后核对：

- 看板任务状态
- 实际分支状态
- Worker 注册表
- 文件锁
- 待验收报告
- 测试是否通过

发现不一致时，以代码、提交历史和测试结果为依据修正文档。

## 6. 不允许发生的情况

- Codex 口头说完成，但没有提交和报告
- Claude 自动记忆里有决定，但仓库里没有
- 两个主控同时修改全局状态
- Worker 自己把任务标为 DONE
- 工具切换时遗留未提交修改却不说明

## 7. 推荐交接摘要

```text
当前主分支提交：
已完成任务：
进行中任务：
活跃 Worker：
待验收：
阻塞：
文件锁：
下一步：
最后一次全量测试：
```

## 8. 当前接手快照

更新日期：2026-07-09

```text
当前主分支提交：f4e24c9 fix: defer outreach sending after approval
当前分支：main
已完成任务：T01-T22；DeepSeek 筛选、Campaign 资格判断、飞书 LLM 审核、飞书话术审批入库
进行中任务：用旧数据继续验证真实闭环；暂不做新的小红书采集
活跃 Worker：无长期常驻 worker
待验收：approved_to_send 后的受控小红书发送入口；feishu-ai-review-sync 挂入控制台/worker；长期稳定运行
阻塞：当前浏览器/网络环境无法稳定打开小红书私信页，用户要求不要改 Clash
文件锁：无
下一步：先完善旧数据闭环和飞书审核/审批体验，再恢复真实发送
最后一次全量测试：.venv/bin/pytest -q -> 301 passed, 4 skipped, 1 warning
```

接手时不要以旧功能分支为主线。除非用户明确要求新分支，默认在 `main` 上继续提交并推送。
