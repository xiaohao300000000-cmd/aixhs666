# V16 Task Productization Verification

## Scope

交付 `screen_historical_leads` 的飞书任务中心纵向闭环。PostgreSQL 为事实源，Worker 直接调用 Python service；不访问小红书，不发送评论或私信。

## Real Acceptance Steps

1. 执行 `alembic upgrade head`，确认 `skill_runs` 与 `skill_run_events` 存在。
2. 配置 Feishu IM、`FEISHU_VERIFICATION_TOKEN`、回调地址；可选配置 `FEISHU_SKILL_RUN_TABLE_ID`。
3. 执行 `aixhs feishu-task-center --chat-id <CHAT_ID>`。
4. 点击“创建任务”，填写范围、数量、Campaign，点击“预览任务”。
5. 核对候选数量，点击“确认运行”，确认回调在 3 秒内返回官方 toast/card 响应。
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

### Interaction Correction — 2026-07-15

- 用户真实点击旧版 Card 2.0 按钮返回 `200671`。普通按钮缺少 `behaviors.callback`、表单按钮错误使用 `action_type` 的问题已先行修复。
- 2026-07-15 重启旧 API 时读取到此前真实请求日志：`skill_create_screen_historical_leads` 已到达现有 HTTP 回调，但动作位于 `event.action.value.action`；旧代码只读 `event.action.name`，因此误入 LLM 审核并返回 HTTP 400。这是 `200671` 的直接根因，不需要切换长连接或更换应用。
- 路由现返回飞书官方 `toast + card(type=raw)`，不再返回自定义 `code/msg/accepted`；共享的其他卡片动作返回官方 toast。
- 飞书签名算法已修正为 `SHA256(timestamp + nonce + encrypt_key + raw_body)`，并支持外层 `encrypt` AES-CBC 解密。
- 修复后本地原路由探针 HTTP 200 / 0.05 秒，公网原地址探针 HTTP 200 / 0.81 秒，均返回完整 Card 2.0 参数表单；探针事件幂等绑定 Run `#6`。
- 新增 `apps/feishu_task_center_listener.py` 和 `apps/worker/skill_run_service.py`，分别负责快速卡片事件持久化和只领取 `skill_run_execute`，不触碰小红书任务。
- 最新全量测试：`509 passed, 7 skipped, 1 warning in 25.97s`。
- `lulu大王` 仅出现在旧私群成员列表中，不能据此推断它是历史回调应用；此前关于复用 `lulu大王` 的结论错误并已撤回。
- 当前唯一证实的发卡应用是 lark-cli 应用 `cli_aac1e28d6a399bfc`。开发者后台截图确认继续使用原 HTTP 回调地址；不得建议切换回调模式或修改旧配置。
- 协议和公网链路已经自动化验证；按钮闭环仍需用户进行一次真实点击复验后才能标记 LIVE DONE。
- 本机 `.env` 保持测试前的 chat、发送身份和 Base dry-run 配置；V16 Listener/专用 Worker停止，原 API 与原 HTTP 公网隧道继续运行。

### Create Task Live Success — 2026-07-15

- 应用 `cli_aac1e28d6a399bfc` 已发布 `1.0.2`，保留原 HTTP 回调地址和 `card.action.trigger`。
- 发布后首次新卡点击仍未进入 API；应用身份、订阅和加密策略均已排除。
- 停止并以相同 `--subdomain three-emus-kick` 重启 localtunnel，没有修改开发者后台地址。
- 新卡 `om_x100b6a5c096318a4b1ca479dccbd4b8` 真实点击成功；飞书服务器请求进入 FastAPI 并返回 HTTP 200。
- PostgreSQL 创建 `Skill Run #8`，状态 `draft`，真实用户、chat 和 message 绑定正确。
- 结论：代码层根因包括动作解析和响应格式；最终无请求问题来自失效/异常的 localtunnel 会话。开发验收必须同时检查应用配置、线上版本、API 日志和隧道会话。
- 专门 Runbook：`docs/FEISHU_CARD_CALLBACK_RUNBOOK.md`。
