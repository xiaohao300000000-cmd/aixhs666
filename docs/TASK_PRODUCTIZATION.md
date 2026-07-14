# V16 飞书任务中心与 Skill Runtime

## 1. 目标

V16 把已经存在的后端能力包装成普通运营人员可理解、可预览、可执行、可追踪的飞书任务产品。第一版只交付一个纵向闭环 Skill：

```text
screen_historical_leads / 历史线索智能筛选
```

最终用户流程：

```text
飞书任务中心
→ 选择“历史线索智能筛选”
→ 填写参数
→ 查看任务预览
→ 确认运行
→ 卡片显示阶段进度
→ 完成后显示处理数量、有效需求、高意向客户、待确认数量和飞书同步结果
```

该 Skill 只读取本地 PostgreSQL 中已经存在的帖子、评论、用户和筛选结果，直接复用 DeepSeek 主筛选、Campaign 资格判断和飞书 AI Review 同步 Python service。它不得访问小红书，不得发送评论或私信，不得通过 subprocess 调用项目 CLI。

## 2. 方案比较

### 方案 A：把“系统控制台”改名并增加动作

优点是改动少。缺点是控制台仍是 Base 行驱动的一次性管理员入口，没有预览、阶段事件、同卡进度、取消、重试和复制语义，无法形成普通运营产品闭环。

### 方案 B：只增加 `skill_runs` 表并由 CLI 执行

优点是数据模型简单。缺点是飞书仍只是触发器，运行逻辑和进度留在 CLI，违反“不通过 subprocess 调用 CLI”和“同一张任务卡片展示阶段进度”的要求。

### 方案 C：独立 Skill Runtime，CollectionTask 只做投递

这是本轮采用的方案。`SkillRun` 是产品任务事实源，`SkillRunEvent` 是审计和进度时间线，静态 Registry 描述可用 Skill，`services/skill_runtime.py` 负责状态机和阶段执行，现有 Worker 只通过 `skill_run_execute` CollectionTask 唤醒 Runtime。飞书任务卡片是操作界面，PostgreSQL 是最终事实源。

## 3. 核心边界

### 3.1 Skill

Skill 是一个静态注册的、面向运营的任务定义，包含：

- 稳定键：`screen_historical_leads`
- 中文名称：`历史线索智能筛选`
- 版本：首版 `1`
- 参数 schema
- 可预览能力
- 阶段定义
- 结果摘要字段
- 是否允许取消、重试和复制
- Python handler

第一版用 Python Registry，不开发 Skill 管理后台，不允许运营人员上传任意代码或命令。

### 3.2 Skill Run

Skill Run 是一次具体业务任务，是 PostgreSQL 中的事实记录。它保存：

- Skill 键和版本
- 参数、预览、checkpoint、结果摘要
- 当前状态、阶段、进度
- 请求人、飞书 chat/message 绑定
- 幂等键、复制来源、重试次数
- 取消请求、开始/完成时间和明确错误

Skill Run 不等同于 Pipeline Run。Pipeline Run 表示一次工程 Pipeline 调用；Skill Run 表示运营人员看到和管理的一次产品任务。一个 Skill 可以直接复用多个现有 service，也可以在未来调用 Pipeline Runner，但二者状态机不得混用。

### 3.3 Skill Run Event

Skill Run Event 是只追加时间线，用于审计、恢复和卡片进度展示。事件至少包括：

- `created`
- `parameters_updated`
- `previewed`
- `queued`
- `started`
- `stage_started`
- `progress`
- `cancel_requested`
- `cancelled`
- `failed`
- `retry_queued`
- `completed`
- `copied`
- `feishu_card_updated`
- `feishu_card_update_failed`

回调事件 ID 作为可空唯一 `event_key` 保存，用于重复点击和回调重放幂等。

### 3.4 CollectionTask

CollectionTask 继续承担 Worker 的通用领取、心跳、超时恢复和调度能力，但只作为执行投递层：

```text
task_type=skill_run_execute
target_id=<skill_run_id>
max_attempts=1
```

Skill Run 的业务状态不能由 CollectionTask 状态推断。Worker 重启或任务超时后，新 Worker 读取 Skill Run checkpoint 恢复；CollectionTask 自身不得复制业务结果或替代 Skill Run Event。

### 3.5 飞书任务卡片

飞书卡片是 Skill Run 的操作界面，不是事实源。卡片包含目录、参数表单、预览、确认、进度、失败恢复和结果视图。

同一个 Skill Run 从参数填写到完成结果持续更新同一条飞书消息。回调 delayed-update token 只用于点击后的即时更新，因为 token 只有短期有效且使用次数有限；Worker 使用飞书“更新应用发送的消息”接口按 `message_id` PATCH 完整卡片内容。

### 3.6 飞书多维表格

PostgreSQL 保存完整 Skill Run 和事件。可选配置“任务运行记录”Base 表作为运营历史视图，字段只包含任务名称、状态、阶段、进度、请求人、参数摘要、结果摘要、错误、开始和完成时间、系统记录编号。Base 写入失败只记录同步错误，不改变 Skill Run 最终业务状态，也不得重跑 DeepSeek。

## 4. 数据模型

### 4.1 `skill_runs`

主要字段：

- `id`
- `skill_key`
- `skill_version`
- `status`
- `current_stage`
- `progress_current`
- `progress_total`
- `progress_percent`
- `parameters_json`
- `preview_json`
- `checkpoint_json`
- `result_summary_json`
- `error_code`
- `error_message`
- `requested_by`
- `idempotency_key`
- `feishu_chat_id`
- `feishu_message_id`
- `feishu_card_status`
- `feishu_sync_error`
- `copied_from_run_id`
- `retry_count`
- `cancel_requested_at`
- `started_at`
- `finished_at`
- `created_at`
- `updated_at`

约束：

- `idempotency_key` 唯一。
- `status`、`current_stage` 建索引。
- `copied_from_run_id` 自关联并在删除来源时置空。
- JSON 字段只保存可重放的业务参数和结果，不保存飞书 token、DeepSeek key 或其他凭据。

### 4.2 `skill_run_events`

主要字段：

- `id`
- `skill_run_id`
- `sequence`
- `event_key`
- `event_type`
- `stage`
- `status`
- `message`
- `progress_current`
- `progress_total`
- `data_json`
- `created_at`

约束：

- `(skill_run_id, sequence)` 唯一。
- `event_key` 可空唯一。
- 删除 Skill Run 时级联删除事件。

## 5. 状态机

Skill Run 状态：

```text
draft
→ previewed
→ queued
→ running
→ succeeded

draft / previewed / queued / running(cancel-safe stage)
→ cancel_requested
→ cancelled

queued / running
→ failed
→ queued (explicit retry)
```

规则：

- `draft`：已创建并绑定飞书卡片，等待参数。
- `previewed`：参数已校验并生成只读预览，尚未运行 DeepSeek。
- `queued`：人工确认运行，已创建一个持久 Worker task。
- `running`：Worker 已领取。
- `cancel_requested`：运行中的可中断阶段收到取消请求；当前单条外部调用结束后停止。
- `cancelled`：未进入不可中断阶段或已在安全 checkpoint 停止。
- `failed`：明确失败，保存错误码和可理解错误；只有人工按钮可以重试。
- `succeeded`：所有阶段完成并保存结果摘要。飞书卡片或 Base 同步失败可作为摘要中的同步失败，不回退 DeepSeek 结果。

不可中断阶段为 `sync_feishu`。进入该阶段后取消按钮不可用，避免部分外部写入造成不一致。`screen` 阶段可在每条历史记录之间响应取消，但不能中断已经发出的单次 DeepSeek HTTP 请求。

## 6. `screen_historical_leads` 参数

第一版参数：

- `data_range`：`all`、`last_30_days`、`last_90_days`
- `source_types`：`content_and_comment`、`content_only`、`comment_only`
- `limit`：1–500，默认 50
- `campaign_id`：来自 `configs/campaigns/*.json` 的静态可用 Campaign

普通运营卡片使用中文标签：

- 数据范围
- 数据来源
- 最多处理数量
- Campaign

预览只查询 PostgreSQL，不调用 DeepSeek，不写飞书 AI Review 表。预览显示：

- 符合范围的历史记录数
- 本次最多处理数
- 已有有效筛选结果、将跳过的数量
- 预计需要 DeepSeek 处理的数量
- Campaign 名称和地区策略摘要

## 7. 阶段执行

### 7.1 `prepare`

- 重新校验参数和 Skill 版本。
- 按时间范围和来源类型选出候选 `(entity_type, entity_id)`。
- 按确定顺序截取 `limit`。
- 将候选列表和 `next_index=0` 写入 checkpoint。
- 记录 `stage_started` 和预备结果事件。

### 7.2 `screen`

- 从 checkpoint 的 `next_index` 开始逐条处理。
- 每条直接调用 `run_llm_lead_screening` 的 Python API，传入确切 entity type/id 和本次 Campaign。
- 每条完成后提交数据库、更新 checkpoint 和进度事件。
- Worker 重启后从下一条继续；已产生非 pending 筛选结果的记录由现有幂等规则跳过。
- 在每条开始前检查取消请求。

为了允许任务参数选择 Campaign，`run_llm_lead_screening` 增加可选 `campaign` 参数；未传时保持现有环境配置行为，兼容 CLI 和其他调用方。

### 7.3 `sync_feishu`

- 标记为不可中断阶段。
- 只同步本次涉及的 `LeadScreeningResult` ID。
- 直接调用 `sync_feishu_ai_review_rows` Python API，不调用 CLI/subprocess。
- 记录 customers/evidence created/updated/skipped/failed。

`sync_feishu_ai_review_rows` 增加可选 `screening_ids` 过滤参数；未传时保持现有增量同步行为。

### 7.4 `summarize`

结果摘要至少保存：

- `processed_count`
- `valid_demand_count`
- `high_intent_count`
- `needs_review_count`
- `failed_count`
- `skipped_existing_count`
- `feishu_sync`

高意向按现有 `intent_strength=high` 统计；有效需求按 `review_status=accepted` 统计；待确认按 `review_status=needs_review` 统计。

## 8. 静态 Skill Registry

Registry 使用 Python 定义，启动时校验：

- Skill key 唯一。
- 版本为正整数。
- 阶段名称唯一且顺序固定。
- 参数 schema 可解析。
- handler 已注册。

第一版只注册 `screen_historical_leads`。未知 Skill key、未知 Campaign、超出 limit、非法枚举和空参数都在创建预览前被拒绝。

## 9. 飞书任务中心交互

### 9.1 任务目录

通过 Python service/CLI 发送“飞书任务中心”目录卡到指定 chat。目录卡展示可用任务，并提供“创建历史线索智能筛选”按钮。现有“系统控制台”继续保留为管理员兼容入口。

### 9.2 创建与参数

点击创建后：

- 回调验证 token、操作人、message/chat 绑定和事件幂等。
- 创建 `draft` Skill Run 并绑定当前卡片。
- 回调快速返回 `accepted`。
- 使用 delayed-update token 把当前卡片改为参数表单。

参数表单包含范围、来源、数量和 Campaign。提交后保存参数、生成预览并把卡片改为预览状态。

### 9.3 确认运行

点击确认后：

- 条件更新 `previewed → queued`。
- 创建一个 `skill_run_execute` CollectionTask。
- 记录 `queued` 事件。
- 回调快速返回 `accepted`，不得调用 DeepSeek、Campaign 执行或完整同步。

重复点击只返回当前持久化状态，不创建第二个 Skill Run 或第二个 CollectionTask。

### 9.4 进度与结果

Worker 在阶段开始、进度 checkpoint、失败、取消和完成时渲染完整卡片，并按 `feishu_message_id` 更新同一条消息。

完成卡片显示：

- 处理数量
- 有效需求
- 高意向客户
- 待确认数量
- 失败/跳过数量
- 飞书同步结果

### 9.5 取消、重试、结果和复制

- 取消：只对 `draft`、`previewed`、`queued` 和处于可中断阶段的 `running` 开放。
- 重试：只对 `failed` 开放，复用 checkpoint 并增加 `retry_count`，创建一个新执行 task。
- 查看结果：展示持久化结果摘要和最近阶段事件。
- 复制任务：创建新的 `draft` Skill Run，复制参数和预览，记录 `copied_from_run_id`，并在同一 chat 发送一张新的任务卡片，不覆盖原完成卡。

## 10. Worker 恢复与幂等

- CollectionTask 使用已有 `FOR UPDATE SKIP LOCKED` 和 Worker timeout 恢复。
- Runtime 对 `queued`、`running`、`cancel_requested` 都可安全重新进入。
- 每条历史记录处理后提交 checkpoint，避免 Worker 重启后从头开始。
- 同一回调 `event_key` 只应用一次。
- 确认运行通过 Skill Run 状态条件更新保证只创建一个执行 task。
- 明确失败不会自动重试；只有卡片“重试”操作创建新 task。
- Feishu message 更新失败记录事件和 `feishu_sync_error`，不改变 Skill Run 业务状态。

## 11. API 与服务边界

新增服务：

- `services/skill_registry.py`：静态定义、参数 schema、Campaign 列表。
- `services/skill_runtime.py`：创建、预览、排队、执行、取消、重试、复制、事件和摘要。
- `services/feishu_task_center.py`：卡片渲染、发送、message patch、回调解析与应用。

新增 Worker task handler：

- `apps/worker/skill_run.py`

现有服务扩展：

- `run_llm_lead_screening(..., campaign: CampaignConfig | None = None)`
- `sync_feishu_ai_review_rows(..., screening_ids: set[int] | None = None)`
- `FeishuIMClient.patch_interactive_message(message_id, card)`

飞书回调路由只识别并调用任务中心回调 service；所有重逻辑由 Worker 执行。

## 12. 测试策略

自动测试必须覆盖：

- Registry 和参数校验。
- Skill Run 状态转换和非法转换。
- Preview 不调用 LLM。
- 回调 event ID 幂等和重复点击。
- 确认运行只创建一个 CollectionTask。
- Worker 重启后从 checkpoint 恢复。
- 阶段事件顺序和进度。
- 明确失败后的人工重试。
- 可中断阶段取消和不可中断阶段拒绝取消。
- 飞书目录、参数、预览、进度、失败和结果卡片渲染。
- 同一 `message_id` 的完整卡片 PATCH。
- 结果摘要统计。
- `run_llm_lead_screening` Campaign override 兼容性。
- `sync_feishu_ai_review_rows` screening ID 过滤。
- 不访问小红书、不构造评论或私信 sender。

完成后运行：

```bash
.venv/bin/python -m pytest -q
git diff --check
```

## 13. 明确不做

- 不新增小红书采集。
- 不运行 live selector probe。
- 不发送真实评论或私信。
- 不修改现有真实发送状态机。
- 不新增获客算法。
- 不开发 Skill 管理后台。
- 不允许自定义脚本或任意命令执行。
- 不把现有系统控制台改名为任务中心。
