# 小红书评论回复运营与安全验收手册

## 当前验收状态

- **自动化实现：完成。** 数据模型、迁移、草稿生成、飞书卡片审批、`approved_to_send` 持久任务、Worker 独立发送、远程 Windows CDP、客户跟进同步、恢复/认领命令和自动测试均已实现；2026-07-14 全量测试为 `494 passed, 7 skipped, 1 warning`。
- **真实发送验收：阻塞。** 截至 2026-07-13，Windows CDP/SSH 当前不可用，且未提供专用测试 URL、评论 ID、内容 ID、最终批准文本和客户跟进 Base live 配置，因此不得声称真实发送成功。
- **解除阻塞条件：** 恢复 Windows Chrome CDP；准备一个允许测试的目标帖子/评论和最终回复文本；先运行不提交的 selector probe；人工在飞书明确批准本次单条测试；最后才允许执行一次真实发送。

## 安全边界

1. 只回复一条明确评论，不发布无目标一级评论，不批量发送。
2. 生产评论回复必须复用远程 Windows Chrome 的持久登录 context；远端不可用时不得静默回退到 Mac 本地浏览器。不绕过登录、验证码、权限或平台风控。
3. selector probe 可点击目标评论的“回复”以展开编辑器和提交控件，但**不得填写文本或点击提交**。
4. 真实发送只允许一次点击。`sent` 禁止重发；`result_unknown` 禁止盲目重试，必须先人工打开目标页面核对。
5. 飞书回调收到重复事件时只返回已持久化状态，不得再次发送。
6. 客户跟进表同步失败与小红书发送相互隔离；同步重试不得触发平台重发。
7. 仓库、日志、截图、文档和测试中不得写入凭据、Cookie、真实目标 URL、评论 ID 或批准文本。

## 数据库与迁移

```bash
python -m alembic upgrade head
```

迁移 `0015_lead_comment_replies` 新增 `lead_comment_replies`，并为 `leads` 增加 `followup_status`、`next_followup_at`。主要状态为 `pending_review`、`approved_to_send`、`sending`、`sent`、`failed`、`result_unknown`；同一筛选结果和同一平台评论均保持唯一，防止重复建卡或重复回复。

## 精确环境配置

常规运行使用 `.env`，实际值只保存在本机：

```dotenv
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DB
XHS_BROWSER_PROFILE_DIR=.runtime/xhs-profile
XHS_HEADLESS=false
XHS_SNAPSHOT_DIR=.runtime/snapshots
XHS_SCREENSHOT_DIR=.runtime/screenshots
XHS_PAGE_TIMEOUT_MS=30000
XHS_MANUAL_LOGIN_TIMEOUT_MS=120000
XHS_PROXY_SERVER=
COMMENT_REPLY_BROWSER_MODE=remote_cdp
COMMENT_REPLY_CDP_URL=http://WINDOWS_TAILSCALE_IP:RELAY_PORT
COMMENT_REPLY_GENERATION_API_KEY=
COMMENT_REPLY_GENERATION_MODEL=deepseek-v4-flash
COMMENT_REPLY_GENERATION_API_URL=https://api.deepseek.com
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_VERIFICATION_TOKEN=
FEISHU_ENCRYPT_KEY=
FEISHU_LLM_REVIEW_CHAT_ID=
FEISHU_IM_TRANSPORT=openapi
FEISHU_CUSTOMER_FOLLOWUP_APP_TOKEN=
FEISHU_CUSTOMER_FOLLOWUP_TABLE_ID=
FEISHU_CUSTOMER_FOLLOWUP_TIMEZONE=Asia/Shanghai
FEISHU_BITABLE_TRANSPORT=openapi
```

`COMMENT_REPLY_GENERATION_API_KEY` 为空时生成器可回退到 `DEEPSEEK_API_KEY`。真实评论回调必须配置非空 `FEISHU_VERIFICATION_TOKEN`；缺失或空值时接口返回配置错误，并且不会识别或执行评论回复动作。若 verification token 已配置，而签名或 encrypt key 未配置，则继续遵循项目现有飞书回调合同，不额外破坏其他 legacy 回调。禁止把任何实际值提交到 Git。

`COMMENT_REPLY_BROWSER_MODE=remote_cdp` 只支持 Chromium，并要求 `COMMENT_REPLY_CDP_URL` 指向通过 Tailscale 安全暴露的 Windows Chrome DevTools 地址。发送器通过 `connect_over_cdp` 复用第一个现有 browser context，不关闭远端 context，也不会在 Mac 启动本地浏览器。连接失败必须明确记录为任务错误，不允许自动切换到 `local`。`local` 只保留给开发和既有自动测试。

## 飞书 Base 字段、视图与仪表盘

客户跟进表必须包含以下字段：

| 类型 | 字段 |
|---|---|
| 系统维护 | `客户唯一键`、`评论审批状态`、`评论发送结果`、`最近评论时间`、`最近评论错误`、`评论回复记录 ID`、`审批卡片消息 ID` |
| 人工维护 | `当前客户状态`、`负责人`、`运营备注`、`下次跟进时间` |

自动状态映射：`pending_review=评论待审核`、`approved_to_send=评论已批准，等待发送`、`sending=评论发送中`、`sent=已评论引导，等待客户私信`、`failed=评论发送失败`、`result_unknown=评论结果待确认`。人工终态 `已收到私信`、`沟通中`、`已成交`、`已忽略` 不得被自动同步回退。

建议建立 `评论待审核`、`评论发送失败`、`评论结果待确认`、`已评论待私信` 和按 `当前客户状态` 分组的 `人工跟进看板`。仪表盘至少显示待审核数、发送失败数、结果待确认数、已评论待私信数，以及按负责人/客户状态分组的跟进量。视图和仪表盘链接只记录在内部安全位置，不写入测试或公开日志。

## 启动与日常运行

```bash
python -m uvicorn apps.api.main:create_app --factory --host 0.0.0.0 --port 8000
python -m apps.worker
python -m apps.cli comment-reply-generate-once --screening-id SCREENING_ID --chat-id CHAT_ID
```

人工在飞书卡片检查原帖、目标评论和回复文本，编辑后点击确认。处理流程为：

```text
人工在飞书确认最终文本
→ 回调校验 token、操作人、消息和 chat 绑定
→ 状态写为 approved_to_send
→ 创建一个 comment_reply_send 持久任务
→ 回调立即返回 accepted
→ Worker 条件领取并写为 sending
→ 通过 Windows Chrome CDP 执行一次发送
→ 持久化 sent / failed / result_unknown
→ 更新飞书结果卡片
→ 独立同步客户跟进表
```

客户跟进同步失败时只运行：

```bash
python -m apps.cli comment-reply-sync-followup --reply-id REPLY_ID
```

评论回复发送位于独立持久任务路径。回调 acceptance gate 必须验证：请求快速返回 `accepted`；回调进程不构造 Playwright sender；重复回调只读取已持久化状态；数据库中只有一个 `comment_reply_send` 任务。Worker acceptance gate 单独验证状态领取、`attempt_count` fencing、远程 CDP 复用和最终状态持久化。飞书/Base 同步重试不得调用平台发送器。

## 卡片恢复、发送恢复与认领

对卡片创建或发送长时间停在处理中状态时，先执行只判定、不重发的恢复命令：

```bash
python -m apps.cli comment-reply-reconcile-stale --reply-id REPLY_ID \
  --card-timeout-seconds 300 --send-timeout-seconds 300
```

陈旧建卡 claim 必须先在飞书确认是否已有卡片。若已存在且消息 ID 可验证，使用认领命令，不再创建第二张卡：

```bash
python -m apps.cli comment-reply-adopt-card --reply-id REPLY_ID \
  --message-id VERIFIED_MESSAGE_ID --chat-id VERIFIED_CHAT_ID \
  --operator OPERATOR_ID --reason "verified existing card after reconciliation"
```

认领只修复卡片关联，不发送小红书评论。陈旧发送 claim 进入 `result_unknown`；若无法确认远端结果，保持 unknown 并交由人工核对。

只有人工确认平台上确实没有发送成功后，才允许显式执行：

```bash
python -m apps.cli comment-reply-confirm-not-sent --reply-id REPLY_ID \
  --operator OPERATOR_ID --reason "checked target comment and confirmed reply absent"
```

该命令只允许条件更新 `result_unknown -> failed`，并把 operator/reason 写入审计错误字段；它不会自动发送。由于飞书现有 API 只能凭回调临时 update token 更新原卡，CLI 无法按持久化 message ID 安全改写旧卡，因此命令会在原 chat 中创建一张带 `retry_comment_reply_ID` 动作的新重试卡，并在明确收到新 `message_id` 后替换数据库绑定。只有新卡回调能通过 message/chat 校验并领取新 attempt，旧卡按钮会被拒绝。

CLI JSON 会返回 `card_status`：`replaced` 表示新重试 UI 已绑定；`replacement_unknown` 表示发送异常或未返回 message ID，数据库虽然已保留为 `failed`，但 UI 恢复未完成，命令退出码为 `2`，并在 `card_error` 给出人工核对信息。`retry_card_creating` 是持久化防重 claim；未知结果下禁止再次建卡，必须先在飞书消息历史核对是否已生成替代卡，再由后续显式认领/修复流程处理。之后仅允许普通 `retry` 回调重新领取一个新 attempt。旧 attempt 的迟到完成会因 `attempt_count` fencing 被拒绝，不能覆盖新 attempt。

## Selector Probe 与真实验收合同

只读 probe 不会提交：

```bash
XHS_COMMENT_REPLY_SELECTOR_PROBE_URL='prepared target URL' \
XHS_COMMENT_REPLY_SELECTOR_PROBE_COMMENT_ID='prepared comment ID' \
python -m pytest -q tests/test_xhs_comment_reply.py -k live_selector_probe -s
```

真实合同测试默认跳过。只有在同一次人工验收窗口中，准备好专用目标并获得飞书明确批准后，才临时注入以下环境；不得写入 `.env`、shell history、CI secret 或仓库文件：

```bash
XHS_COMMENT_REPLY_LIVE_TARGET_URL='prepared target URL' \
XHS_COMMENT_REPLY_LIVE_TARGET_COMMENT_ID='prepared comment ID' \
XHS_COMMENT_REPLY_LIVE_TARGET_CONTENT_ID='prepared content ID' \
XHS_COMMENT_REPLY_LIVE_APPROVED_TEXT='Feishu-approved text' \
XHS_COMMENT_REPLY_LIVE_FEISHU_APPROVAL='FEISHU_APPROVED_SINGLE_COMMENT_REPLY' \
XHS_COMMENT_REPLY_LIVE_SEND=1 \
python -m pytest -q tests/test_comment_reply_live_contract.py -s
```

合同测试先执行 selector probe，只有目标容器恰好一个、回复按钮/编辑器/提交控件均恰好一个，且两个批准开关完全匹配时才发送一次。任何 probe 失败都必须停止。

## 结果处理

- `sent`：必须有相关平台成功响应或目标评论下可见的新回复证据；更新卡片和客户跟进表，禁止再次发送。
- `failed`：平台明确拒绝，或点击提交前明确失败；可由人工修复后从原卡片重试。
- `result_unknown`：点击已开始，但客户端没有相关成功/失败证据。立即停止自动化并人工查看目标评论、账号通知和平台状态；不得盲目重试。
- 飞书/Base 同步失败：只重试 `comment-reply-sync-followup`，不得调用发送器。

## 上线验收清单

- [ ] 数据库已迁移到 head。
- [ ] 飞书回调校验和 Base 字段/视图已配置。
- [ ] Windows Chrome CDP 已通过 Tailscale 恢复，浏览器已人工登录，且无验证码/风控提示。
- [ ] Worker 已使用 `COMMENT_REPLY_BROWSER_MODE=remote_cdp` 和正确的 `COMMENT_REPLY_CDP_URL` 启动。
- [ ] 使用专门准备的目标，不是普通客户评论。
- [ ] 只读 selector probe 通过并由人工查看报告。
- [ ] 飞书中明确批准最终文本和本次单条发送。
- [ ] 合同测试只执行一次。
- [ ] 平台页面确认回复落在正确评论下。
- [ ] 卡片与客户跟进表状态一致。
- [ ] 若为 `result_unknown`，已停止并记录人工核对，不盲目重试。
