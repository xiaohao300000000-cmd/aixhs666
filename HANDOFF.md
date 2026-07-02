# 当前交接状态

## 当前阶段

V15 Agent 中立运行框架已在 `feat/v15-agent-neutral-runtime` 接通。新增轻量 `PipelineRunner`、`pipeline_runs` 持久化、CLI 和 REST，使框架可以在不依赖 Codex 会话记忆的情况下完成一轮基础采集与分析。完整生产闭环仍因真实小红书 Pipeline Runner 小规模验证、真实飞书凭证和长期无人值守验证未完成而不能写成 100%。

## 当前目标

当前目标是从“模块可用”推进到“Agent 中立完整运行闭环”。代码侧已具备 MediaCrawler 主采集器、Worker、数据库并发/幂等修复、飞书传输/回调、数据库看板、运行诊断、`/ops` 控制台，以及 Pipeline Runner。下一步必须在真实 MediaCrawler 依赖和登录态可用后执行一次小规模 `run-cycle` 验证，再配置 Feishu 凭证并执行真实发送/回调验收。

## 已确认范围

- 第一阶段平台：小红书
- 第一阶段重点：稳定采集、上下文、去重、增量、新词发现
- 保留少量高价值信号飞书预警
- 暂不做自动私信、自动评论、CRM 和多平台

## 需要主控 Codex 完成的下一件事

1. 安装/确认 `third_party/MediaCrawler/.venv` 和持久登录态。
2. 使用 `python -m apps.cli --json run-cycle --query-id <id> --collection-limit 5` 执行真实小红书 Pipeline Runner 验证。
3. 配置 Feishu Webhook 或应用凭证并执行真实发送/回调验收。
4. 运行 Worker 或 Pipeline 小规模长期观察，记录登录态、限流、内存和任务状态。
5. 更新 `docs/V15_AGENT_NEUTRAL_RUNTIME_REPORT.md` 的真实验证结果。

子会话不得直接修改本文件或把任务改为 DONE。

## 当前已知风险

- 真实小红书页面结构已验证一次，但后续仍可能变化
- 当前最新副本未包含可用 `third_party/MediaCrawler/.venv`，真实 Pipeline Runner 验证未完成
- Docker 未安装，当前使用本机 Homebrew PostgreSQL
- 飞书真实发送和真实回调尚未验证
- `pytest -m live` 因未启用 live 登录环境仍为 skipped

这些风险直接影响 V0 完整真实闭环验收，不能把当前状态写成 100% 完成。


## 新电脑与并发计划

- 项目将在新电脑上启动
- 第一轮 T01 已完成
- T01、T02、T03、T04、T05 已完成
- T06 查询管理 API 已完成，独立执行对话：019f1c0d-46a0-7f81-aa27-ffd46120ec90
- T07 小红书搜索采集已完成，提交：84b47e4
- T08 小红书详情采集已完成，提交：e1d33fb
- T09 小红书评论采集已完成，提交：a76cb0d
- T10 断点续传与部分成功已完成，提交：3940496
- T11 高价值内容池已完成，提交：e4d0631
- T12 评论区动态预算已完成，提交：6f36f95
- T13 查询与来源评分已完成，提交：8699b21
- T14 文本处理与低信息标记已完成，提交：8b25692
- T15 语义聚类与新词发现已完成，提交：243181d
- T16 飞书新词审核已完成，提交：cbc43bc
- T17 事件日历已完成，提交：514e8b9
- T18 需求事件链已完成，提交：4d9ef37
- T19 信号新鲜度与飞书预警已完成，提交：e2809b7
- T20 数据看板已完成，提交：fbb8e44
- T21 内容洞察输出已完成，提交：46a1b13
- T22 第二平台评估已完成，提交：9bf7f40
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
