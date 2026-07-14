# V16 Task Productization Verification

## Scope

交付 `screen_historical_leads` 的飞书任务中心纵向闭环。PostgreSQL 为事实源，Worker 直接调用 Python service；不访问小红书，不发送评论或私信。

## Real Acceptance Steps

1. 执行 `alembic upgrade head`，确认 `skill_runs` 与 `skill_run_events` 存在。
2. 配置 Feishu IM、`FEISHU_VERIFICATION_TOKEN`、回调地址；可选配置 `FEISHU_SKILL_RUN_TABLE_ID`。
3. 执行 `aixhs feishu-task-center --chat-id <CHAT_ID>`。
4. 点击“创建任务”，填写范围、数量、Campaign，点击“预览任务”。
5. 核对候选数量，点击“确认运行”，确认回调快速返回 `accepted`。
6. 启动独立 Worker，观察同一张卡片阶段从 prepare/screen/sync_feishu/summarize 更新。
7. 完成卡核对处理数量、有效需求、高意向客户、待确认数量和飞书同步结果。
8. 创建另一任务并在 screen 前取消；人为注入 LLM 失败后明确点击重试；点击复制并修改参数重新预览。
9. 检查 PostgreSQL 事件/断点与可选 Base 运行历史；网络审计确认没有小红书请求。

## Per-file Summary

- `storage/models.py`, `alembic/versions/0016_skill_runs.py`: Skill Run/Event 事实模型与迁移。
- `services/skill_registry.py`: 静态 Skill/Campaign 参数定义。
- `services/skill_runtime.py`: 校验、预览、状态机、阶段、事件、断点、取消、重试、复制和摘要。
- `services/llm_lead_screening.py`, `services/feishu_ai_review_sync.py`: Campaign 与 screening IDs 可复用接口。
- `apps/worker/skill_run.py`, `apps/worker/main.py`: 持久任务 Worker 分发。
- `services/feishu_task_center.py`, `integrations/feishu/im.py`, `apps/api/routes/feishu_callbacks.py`, `apps/cli.py`: 飞书任务中心和同消息更新。
- `services/feishu_skill_run_sync.py`: 可选 Base 运营历史投影。
- `tests/test_skill_models.py`, `tests/test_skill_registry.py`, `tests/test_skill_runtime.py`, `tests/test_feishu_task_center.py`: 核心自动化覆盖。
- 产品、架构、数据模型、路线图、任务、决策、看板和交接文档同步 V16。

## Automated Evidence

- 聚焦测试：`58 passed, 1 warning`（Skill/Feishu/Worker/CLI/复用服务）。
- 最终全量测试：`504 passed, 7 skipped, 1 warning in 25.81s`。
- `python -m compileall`：通过。
- `python -m alembic heads`：`0016_skill_runs (head)`。
- `git diff --check`：通过。
- 禁止项扫描：Skill Runtime/Worker/任务中心无 subprocess 项目 CLI、无小红书适配器或发送器导入。

## Real Acceptance Evidence — 2026-07-14

- 真实 PostgreSQL 从 `0015_lead_comment_replies` 升级到 `0016_skill_runs`，两张事实表创建成功。
- 飞书任务中心真实消息：`om_x100b6a569a7d60a4b04c75cc36b0d05`，群：`oc_1623b52748f4cf5cfb6f6e9174008f55`。
- Skill Run `#1` 只读取历史评论 `516/515/514`，真实调用 DeepSeek，Worker task `#357` 完成。
- 结果：处理 3、有效需求 1、高意向 0、待确认 3；事件序列覆盖 created/parameters/preview/queued/prepare/screen/sync/succeeded。
- 飞书 AI 审核 Base 实写：客户新增 1、证据新增 1、失败 0；同一消息 PATCH 后显示“新增 2 / 更新 0 / 失败 0”。
- 从飞书重新读取消息确认 `updated=true`，标题为“任务完成”，结果数字与 PostgreSQL 一致。
- 本次未访问小红书、未运行 selector probe、未发送评论或私信。
- 未完成的外部配置：飞书开发者后台回调 URL 与 `FEISHU_VERIFICATION_TOKEN` 尚未配置，因此真实按钮点击回调未纳入本次验收。

### Visibility Correction — 2026-07-15

- 原目标 `oc_1623b52748f4cf5cfb6f6e9174008f55` 实际是名为“张兆尊”的私有单人群，并非正常机器人单聊；消息虽可由 API 读取，但用户未在当前会话列表看到。
- 通过 bot 对用户 `open_id` 直发后建立真实 P2P 会话 `oc_db1d787a662278e05ce8a5c035a66ee0`。
- 在新会话真实读取确认三条可见消息：测试文本 `om_x100b6a52a2b3c8a4b3b4af6f8625da5`、任务中心 `om_x100b6a52a3f2c0a0b2a11638703fcbd`、Run #1 完成结果 `om_x100b6a52a19c6ca4b14bcd52009fe1d`。
- 本机 `.env` 已把默认 chat 改为该 P2P 会话，并把 `FEISHU_LARK_CLI_AS` 改为 `bot`。
- 后续验收必须同时满足“目标用户 P2P/群成员正确”和“用户身份读取到消息”，不得仅凭发送 API 成功判定用户已收到。
