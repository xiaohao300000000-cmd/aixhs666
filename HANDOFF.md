# 当前交接状态

## 当前阶段

阶段 0 已开始，T01 仓库骨架已验收完成。

## 当前目标

继续派发并验收 `T02 核心数据模型` 和 `T04 PlatformAdapter 与 Mock 采集器`。

## 已确认范围

- 第一阶段平台：小红书
- 第一阶段重点：稳定采集、上下文、去重、增量、新词发现
- 保留少量高价值信号飞书预警
- 暂不做自动私信、自动评论、CRM 和多平台

## 需要主控 Codex 完成的下一件事

1. 创建 `orchestration/briefs/T02.md`，分支 `task/T02-core-data-models`
2. 创建 `orchestration/briefs/T04.md`，分支 `task/T04-platform-adapter-mock`
3. 分别启动独立执行对话 W1、W2
4. 等待 `orchestration/reports/T02.md` 和 `orchestration/reports/T04.md`
5. 验收、合并并推送每个任务
6. T02/T04 均完成后继续 T03 和 T05

子会话不得直接修改本文件或把任务改为 DONE。

## 当前已知风险

- 真实小红书页面结构和登录态尚未验证
- 具体对象存储供应商尚未最终确定
- 飞书字段尚未固定
- 模型供应商尚未确定

这些风险不影响阶段 0 的 T02/T04。


## 新电脑与并发计划

- 项目将在新电脑上启动
- 第一轮 T01 已完成
- 下一轮主控优先并行派发 T02 和 T04
- 默认启用 W1、W2 两个 Worker
- 稳定后可增加 W3
- W4 仅在低冲突阶段启用
- 具体规则见 `docs/CONCURRENCY_POLICY.md`


## AI 工具接手方式

- Codex 主控入口：`MASTER_CODEX_PROMPT.md`
- Claude Code 主控入口：`CLAUDE_MASTER_PROMPT.md`
- Claude Code 持久规则：`CLAUDE.md`
- 两种工具交接：`docs/AGENT_HANDOFF.md`

## 对话启动方式

- 项目经理对话持续保留
- 每个任务单独新开一个独立执行对话
- 独立执行对话不从项目经理对话派生
- 所需上下文由项目经理写入任务包
