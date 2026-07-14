# AI 教育需求发现与获客效率系统

## 1. 项目简介

本项目用于从小红书等公开平台持续发现教育相关需求，采集帖子、评论、回复和公开主页信息，建立可追溯的数据资产，并逐步提升获客效率。

当前最新形态是“本地采集与分析系统 + DeepSeek 筛选 + Campaign 资格判断 + 飞书人工审核/话术审批工作台”：

- 系统负责采集、入库、初筛、生成证据。
- 飞书负责人工查看、确认、忽略、审批跟进话术和发出一次性操作指令。
- 人不需要理解技术词，只在飞书里看 `需求摘要`、`状态`、`结果` 等字段。

项目第一阶段不追求自动销售，而是先解决四件事：

1. 稳定获得足够多的公开需求数据
2. 保存完整上下文和发现路径
3. 自动发现新的搜索词、需求场景和高价值来源
4. 对少量高价值信号进行人工预警和验证

2026-07-06 已验证的飞书工作台：

| 模块 | 链接 |
|---|---|
| 系统控制台 | <https://my.feishu.cn/base/RVtDb7nGkabAMbsDkA0cvxdOnld?table=tblpqsBvrDMWhaiW> |
| 待人工确认卡片 | <https://my.feishu.cn/base/RVtDb7nGkabAMbsDkA0cvxdOnld?table=tblAHiwa7ip0IkxQ&view=vewdlqeDmH> |
| AI 筛选客户线索 | <https://my.feishu.cn/base/RVtDb7nGkabAMbsDkA0cvxdOnld?table=tblAHiwa7ip0IkxQ> |
| AI 筛选证据明细 | <https://my.feishu.cn/base/RVtDb7nGkabAMbsDkA0cvxdOnld?table=tblWuVvYREtAPHGs> |

长期目标是形成一套可迁移到装修、留学、移民、本地生活等行业的“公开市场需求感知引擎”。

2026-07-14 当前工作区：

- GitHub 主分支：`main`
- 远端 `main` 最新提交：`26931d7 Merge pull request #1 from xiaohao300000000-cmd/feat/approved-comment-replies`
- 当前未提交工作区完整测试：`494 passed, 7 skipped, 1 warning`
- 当前不再把新更新只推到功能分支；主线代码已合并并推送到 `origin/main`。
- 小红书真实私信发送暂时搁置：当前本机浏览器/网络环境无法稳定打开小红书私信页，且用户要求不要改 Clash。飞书“发送”按钮已改为只审批入库为 `approved_to_send`，不再在飞书回调线程里直接触发小红书发送。后续等浏览器/网络问题解决后，再通过独立发送入口或 worker 执行真实发送。
- 小红书评论回复同样通过独立持久任务执行：飞书确认后快速返回，Worker 复用 Tailscale 上的 Windows Chrome CDP；不在 Mac 本机另开浏览器。真实单条验收必须先恢复远程发射器并完成只读 selector probe。

## 2. 核心价值

系统不是简单搜索“谁想报班”，而是持续识别需求正在形成的信号，例如：

- 孩子英语跟不上
- KET/PET 考试失败、压线、准备二刷
- 家长比较机构、老师、价格和课程
- 对现有机构不满意
- 暑假、寒假、报名、出成绩等事件触发的新需求
- 教育博主、考试资讯和竞品评论区中的高浓度需求

## 3. 第一阶段范围

第一阶段只做：

- 小红书搜索结果采集
- 帖子、评论和回复采集
- 公开主页信息的按需补全
- 去重、增量更新和断点续传
- 查询词库和高价值内容池
- 新表达、新关键词和新需求场景发现
- 高价值信号飞书预警
- 简单数据看板
- 人工反馈记录

第一阶段暂不做：

- 自动私信
- 未经飞书人工逐条审批的自动评论
- CRM
- 自动成交预测
- 多账号矩阵运营
- 跨平台用户身份合并
- 复杂多 Agent 系统
- 大规模多平台同时上线

## 4. 工作原则

- 先数据，后评分
- 先稳定，后规模
- 先单平台，后多平台
- 先人工验证，后自动化
- 核心逻辑写进代码和文档，不依赖聊天上下文
- 每次只完成一个明确任务
- 所有重要决策写入 `DECISIONS.md`
- 每次交接更新 `HANDOFF.md`
- Codex 每次开始前必须先读 `AGENTS.md`、`TASKS.md`、`HANDOFF.md`

## 5. 文档导航

- [产品需求](docs/PRD.md)
- [系统架构](docs/ARCHITECTURE.md)
- [评论回复运营与安全验收](docs/COMMENT_REPLY_OPERATIONS.md)
- [数据模型](docs/DATA_MODEL.md)
- [开发路线](docs/ROADMAP.md)
- [验收标准](docs/ACCEPTANCE_TESTS.md)
- [种子查询词](docs/QUERY_SEEDS.md)
- [主控与子会话协议](docs/ORCHESTRATION.md)
- [多子会话并发策略](docs/CONCURRENCY_POLICY.md)
- [新电脑部署指南](docs/NEW_COMPUTER_SETUP.md)
- [Codex 与 Claude Code 交接](docs/AGENT_HANDOFF.md)
- [项目可视化进度表](PROJECT_DASHBOARD.md)
- [Codex 工作规则](AGENTS.md)
- [任务清单](TASKS.md)
- [决策记录](DECISIONS.md)
- [当前交接状态](HANDOFF.md)
- [Codex 启动提示词](CODEX_START_PROMPT.md)

## 6. 推荐仓库结构

```text
education-demand-engine/
├── README.md
├── AGENTS.md
├── TASKS.md
├── HANDOFF.md
├── DECISIONS.md
├── CLAUDE.md
├── CLAUDE_MASTER_PROMPT.md
├── CLAUDE_WORKER_PROMPT.md
├── MASTER_CODEX_PROMPT.md
├── WORKER_CODEX_PROMPT.md
├── CODEX_START_PROMPT.md
├── PROJECT_DASHBOARD.md
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   ├── DATA_MODEL.md
│   ├── ROADMAP.md
│   ├── ACCEPTANCE_TESTS.md
│   └── QUERY_SEEDS.md
├── orchestration/
│   ├── briefs/
│   ├── reports/
│   ├── WORKER_REGISTRY.md
│   └── FILE_LOCKS.md
├── templates/
│   ├── TASK_BRIEF.md
│   └── SUBTASK_REPORT.md
├── apps/
│   ├── api/
│   ├── worker/
│   └── dashboard/
├── collectors/
│   ├── base/
│   ├── xiaohongshu/
│   └── generic_web/
├── intelligence/
│   ├── phrase_discovery/
│   ├── clustering/
│   └── coverage_analysis/
├── scheduler/
├── storage/
├── integrations/
│   ├── feishu/
│   └── n8n/
├── tests/
├── docker-compose.yml
├── .env.example
└── pyproject.toml
```

## 7. 第一次启动

将本启动包放入一个新 GitHub 仓库。

推荐先把 `MASTER_CODEX_PROMPT.md` 交给主控 Codex 会话。主控会话会创建 T01 任务简报，再把任务交给执行子会话。

如果暂时不使用多会话，可以使用 `CODEX_START_PROMPT.md` 让单个 Codex 会话直接执行 T01。

项目进度以 `PROJECT_DASHBOARD.md`、`TASKS.md` 和 `HANDOFF.md` 为准，不以聊天记忆为准。

Claude Code 接手时会读取根目录 `CLAUDE.md`：

- 项目经理使用 `CLAUDE_MASTER_PROMPT.md`
- 执行子会话使用 `CLAUDE_WORKER_PROMPT.md`

Codex 与 Claude Code 的切换规则见 `docs/AGENT_HANDOFF.md`。

## 对话架构

```text
持续存在的项目经理对话
├── 新开独立执行对话 W1
├── 新开独立执行对话 W2
├── 新开独立执行对话 W3
└── 新开独立执行对话 W4
```

独立执行对话不是项目经理对话的派生会话，不共享聊天上下文。项目经理通过 `orchestration/packets/TXX.md` 传递完整任务要求。

## 8. V0 真实数据闭环状态

当前 `main` 已包含真实闭环的代码主干：

- Playwright 小红书 adapter：`collectors/xiaohongshu/`
- 可选 MediaCrawler 小红书 adapter：`collectors/mediacrawler/`
- Worker 入口：`python -m apps.worker`
- PostgreSQL 安全任务领取：`FOR UPDATE SKIP LOCKED`
- `discovery_relations(query_id, content_id)` 唯一约束与 upsert
- 飞书 webhook transport、dry-run、重试、回调幂等处理
- 数据库驱动看板：`GET /dashboard/summary`

本机已自动测试：

```bash
.venv/bin/python -m pytest -q
```

结果：

```text
494 passed, 7 skipped, 1 warning
```

主采集后端固定为 MediaCrawler：

```bash
python -m apps.worker --once
```

默认 `WORKER_ADAPTER=mediacrawler`。该后端通过 `MEDIACRAWLER_HOME` 指向项目内 `third_party/MediaCrawler`，运行其小红书 search 模式并读取 JSONL 输出。MediaCrawler 一次 search 会同时补详情和评论，适配层会缓存这些输出，后续 detail/comment 任务优先复用缓存。

飞书客户跟进表同步：

```bash
python -m apps.cli --json feishu-sync
python -m apps.cli --json feishu-pull-feedback
```

真实同步默认走开放平台应用凭证；如果应用身份没有 Base 写权限，但本机已经安装并授权 `lark-cli`，可改用用户态 CLI：

```bash
FEISHU_ENABLED=true
FEISHU_SYNC_DRY_RUN=false
FEISHU_BITABLE_TRANSPORT=lark_cli
FEISHU_BITABLE_APP_TOKEN=<base_token>
FEISHU_LEADS_TABLE_ID=<table_id>
python -m apps.cli --json feishu-sync
```

当前已验证的客户跟进表是 `RVtDb7nGkabAMbsDkA0cvxdOnld / tblRSEpG7v0bM0WD`。

飞书 AI 筛选工作台增量同步：

```bash
python -m apps.cli --json feishu-ai-review-sync
```

该命令把本地 `lead_screening_results` 中 DeepSeek 已产出的 `accepted` / `needs_review` 结果增量写入飞书 `AI筛选客户线索` 和 `AI筛选证据明细` 两张表。它复用 `feishu_bitable_records` 保存本地记录到飞书记录的映射，重复执行会更新原记录，不会重复创建。默认表 ID：

```text
FEISHU_AI_REVIEW_CUSTOMER_TABLE_ID=tblAHiwa7ip0IkxQ
FEISHU_AI_REVIEW_EVIDENCE_TABLE_ID=tblWuVvYREtAPHGs
```

为兼容当前已经创建好的 Base 字段，DeepSeek、Campaign 和地区信息会写入现有字段，例如 `为什么推荐`、`AI判断`、`置信度`、`证据标题`，不会要求先新增飞书字段。同步 payload 已按运营视角把 `需求摘要`、`意向程度`、`下一步`、`状态`、`证据数量`、`为什么推荐` 放在前面，`客户` 和技术 ID 后移。飞书连接方式仍沿用 `FEISHU_ENABLED`、`FEISHU_SYNC_DRY_RUN`、`FEISHU_BITABLE_TRANSPORT` 和 `FEISHU_BITABLE_APP_TOKEN`。

飞书系统控制台：

```bash
FEISHU_CONTROL_PANEL_BASE_TOKEN=RVtDb7nGkabAMbsDkA0cvxdOnld
FEISHU_CONTROL_PANEL_TABLE_ID=tblpqsBvrDMWhaiW
python -m apps.cli --json run-control-panel-once
```

这条命令只检查一次 `系统控制台` 表，不会后台常驻，也不会自动循环。只有表里有人把 `开始执行` 改成 `是，开始` 的记录才会被处理；处理后系统会把 `开始执行` 改回 `否`，并写入 `现在状态`、`结果` 或 `哪里出错了`。

`系统控制台` 面向非技术用户，页面字段使用普通话：

- `我要做什么`：找新客户、重新整理客户、刷新客户表、同步确认结果、查看系统状态
- `开始执行`：否、是，开始
- `现在状态`：等待开始、正在处理、已完成、出错了
- `要找什么`
- `最多看多少条`
- `结果`
- `哪里出错了`

操作方式：

1. 在飞书 `系统控制台` 新增一行。
2. 选择 `我要做什么`。
3. 把 `开始执行` 改成 `是，开始`。
4. 在本机运行 `run-control-panel-once`。
5. 系统只执行这一次，然后把结果写回飞书。

登录态固化方式：

- 默认 `MEDIACRAWLER_ENABLE_CDP_MODE=true`
- 默认 `MEDIACRAWLER_CDP_CONNECT_EXISTING=false`
- 默认 `MEDIACRAWLER_CDP_HOST=localhost`
- 默认 `MEDIACRAWLER_SAVE_LOGIN_STATE=true`
- 默认 `MEDIACRAWLER_AUTO_CLOSE_BROWSER=false`
- 默认持久 profile：`third_party/MediaCrawler/browser_data/cdp_aixhs_xhs_user_data_dir`

如果小红书只能在另一台 Tailscale Windows 主机上稳定打开，可以让远端主机运行 Chrome CDP，再让本机连接远端 CDP：

```env
MEDIACRAWLER_CDP_CONNECT_EXISTING=true
MEDIACRAWLER_CDP_HOST=100.124.24.8
MEDIACRAWLER_CDP_DEBUG_PORT=19223
```

当前验证过的远端方式是：Windows 主机 `100.124.24.8` 通过计划任务启动 Chrome `127.0.0.1:9222`，再用用户态 relay 暴露 `100.124.24.8:19223 -> 127.0.0.1:9222`，防火墙只允许本机 Tailscale 地址访问。不要把 CDP 端口无认证地暴露到公网或普通局域网。

首次登录时运行：

```bash
python -m scripts.mediacrawler_login
```

手动扫码一次后，后续 Worker 复用同一持久浏览器目录，不应每次重新扫码。仍可显式设置 `WORKER_ADAPTER=xiaohongshu` 使用项目自写 Playwright adapter 做 fallback/debug，但它不再是主采集路径。

首次使用前安装 MediaCrawler 依赖：

```bash
python3.12 -m venv third_party/MediaCrawler/.venv
third_party/MediaCrawler/.venv/bin/pip install -r third_party/MediaCrawler/requirements.txt
```

## 9. AI 自动获客业务闭环

当前产品主页面转为：

```text
http://127.0.0.1:8000/leads
```

`/leads` 面向使用者展示潜在客户，而不是展示采集和聚类过程。系统会把历史和新增的小红书 KET/PET 帖子、评论、公开用户加工成：

- `leads`：潜在客户卡片
- `lead_evidence`：判断依据
- `enrichment_tasks`：待完善信息和后续任务

当前 `/leads` 是客户判断工作台，不是工程看板。列表按 `新鲜度 + 意向 + 可行动性` 分桶：

```text
立即处理
今日内处理
可观察
信息不足
过期/低优先级
```

每张卡片展示业务摘要、为什么推荐、来源角色、线索新鲜度、SLA 建议、证据展开和人工判断动作。人工动作包括：

```text
有效
无效
观察
信息不足
重复
已联系
```

这样使用者可以在同一页面完成“看证据 -> 判断是否值得跟 -> 标记下一步”的闭环。

业务闭环：

```text
帖子/评论
→ 规则做去重、垃圾文本过滤和基础字段提取
→ LLM 根据帖子标题、正文、当前评论、父评论做主判断
→ 结构化写回数据库
→ 有价值或不确定的结果进入 leads 和 lead_evidence
→ 不确定结果标记为 needs_review，等待人工审核
```

当前真实飞书筛选结果：

```text
客户线索总数：71
高意向：10
待人工确认：61
证据明细：72
证据关联：72/72
```

人工确认方式：

- 在 `待人工确认卡片` 视图查看 `需求摘要`。
- 点开 `关联证据明细` 查看原始抓取文本。
- 要跟进就把 `状态` 改成 `可跟进`。
- 不跟进就把 `状态` 改成 `已忽略`。
- 未看完保持 `待确认`。

历史数据回填入口：

```bash
python -m apps.cli --json leads-backfill
```

LLM 主筛选入口：

```bash
python -m apps.cli --json leads-llm-screen
```

运行前需要设置 `DEEPSEEK_API_KEY` 或 `LLM_LEAD_SCREENING_API_KEY`。默认使用 DeepSeek 的 OpenAI 兼容接口：`LLM_LEAD_SCREENING_API_URL=https://api.deepseek.com`、`LLM_LEAD_SCREENING_MODEL=deepseek-v4-flash`。如果传入的是基础地址，系统会自动请求 `/chat/completions`。

只筛评论或只筛帖子：

```bash
python -m apps.cli --json leads-llm-screen --source comment
python -m apps.cli --json leads-llm-screen --source content
```

只重跑某一条本地记录：

```bash
python -m apps.cli --json leads-llm-screen --source comment --source-id 123 --reprocess
```

统一流程入口：

```bash
python -m apps.cli --json lead-flow-once --source comment --limit 1 --chat-id oc_xxx
```

`lead-flow-once` 每次只推进当前应该做的一步，不做后台无人值守调度：

```text
pending_llm -> screening -> llm_done -> pending_feishu -> sending -> sent -> reviewed
```

LLM 步骤会先把记录领取为 `screening`，只把筛选结果写回 `lead_screening_results.workflow_status=llm_done`，不会直接发飞书。下一次统一流程会把需要人工审核的 `llm_done` 推进到 `pending_feishu`；飞书发送模块先把 `pending_feishu` 领取为 `sending`，发送成功后写为 `sent`，普通发送失败恢复为 `pending_feishu`；飞书回调后写为 `reviewed`。`attempt_count` 只在真正领取飞书发送时增加。

如果飞书请求结果不确定，例如请求已经发出后超时，记录会进入 `send_uncertain`，不会被自动重发。`/ops/api/lead-screening/diagnostics` 可以查看 stale `sending`、长期 `pending_llm`、高 `attempt_count` 和 `send_uncertain`；需要人工恢复时，使用受 `OPS_TOKEN` 保护的 `POST /ops/api/lead-screening/{id}/recover`，恢复操作会写入 `lead_screening_manual_recovery` 事件。当前没有实现 exactly-once；飞书发送成功但数据库提交前崩溃时，仍需人工核对。

受控可靠性重放入口是 `python -m scripts.lead_flow_reliability_replay --database-url <postgres_test_url> --reset-test-database`。它只使用 fake LLM 和 fake 飞书，输出 JSON 到 `.runtime/lead-flow-reliability-result.json`。

LLM 筛选结果发到飞书人工审核：

```bash
python -m apps.cli --json feishu-send-llm-reviews --chat-id oc_xxx --limit 1
```

飞书审核卡片只提供三个按钮：`有效`、`无效`、`暂时观察`。点击后回调地址为：

```text
POST /feishu/callback/llm-review
```

回调在配置 `FEISHU_ENCRYPT_KEY` 后会校验飞书签名，在配置 `FEISHU_VERIFICATION_TOKEN` 后会校验 verification token；随后按事件和分析结果幂等处理，更新 `lead_screening_results.human_review_status`，并用回调 token 把原飞书卡片更新为“已处理”。如果配置了 `FEISHU_LLM_REVIEW_DASHBOARD_URL`，卡片会展示多维表格仪表盘入口文字。

2026-07-07 已完成一次真实飞书回调验收：

```text
公网 HTTPS: https://soft-trains-prove.loca.lt/feishu/callback/llm-review
飞书应用版本: 1.0.1 已发布
id=2 点击“有效” -> human_review_status=valid
id=3 点击“无效” -> human_review_status=invalid
id=5 点击“暂时观察” -> human_review_status=watch
callback_events=3
feishu_message_id(id=2)=om_x100b6b8b226fd0a0b3bb325753227a5
feishu_message_id(id=3)=om_x100b6b8b22755ca4b15a8242fc9d1de
feishu_message_id(id=5)=om_x100b6b8b221faca0b2adeec32f61761
feishu_chat_id=oc_1623b52748f4cf5cfb6f6e9174008f55
```

本次真实运行环境未设置 `FEISHU_ENCRYPT_KEY` / `FEISHU_VERIFICATION_TOKEN`，所以真实点击没有启用签名密钥校验；签名校验路径由 `tests/test_feishu_llm_review.py` 覆盖。详细验收记录见 `docs/reports/FEISHU_WORKBENCH_VERIFICATION.md`。

### 跟进话术审批状态

人工把 LLM 审核卡片点为 `有效` 后，系统可以生成小红书跟进话术审批卡并发送到飞书。当前真实发送策略是：

```text
生成话术审批卡 -> 飞书内人工编辑/点击发送 -> approved_to_send -> 后续独立发送入口处理
```

飞书“发送”按钮现在只做审批确认和状态入库，不会在回调请求中直接打开小红书发送。这样可以保证飞书回调快速返回，避免小红书浏览器失败导致卡片按钮卡住。真实小红书发送失败会在后续发送入口里记录为 `failed`、`last_error` 和 `attempt_count`，不会把失败伪造成成功。

规则调整后需要重算自动生成结果时使用：

```bash
python -m apps.cli --json leads-backfill --rebuild
```

新的验收指标：

- 找到多少潜在客户
- 每个客户是否有明确证据
- 多少进入待完善队列
- 多少已经达到可跟进条件

`/ops` 保留为管理员控制台，不作为普通运营入口。普通运营使用 `/leads` 或飞书客户审核表；运营负责人通过飞书 `系统控制台` 触发一次性动作；管理员和工程师才进入 `/ops` 处理 worker、任务、错误、恢复和重试。聚类、查询评分和内容洞察继续作为后台能力，用于帮助系统找到更多高质量线索，不再作为主要产品结果展示。

## 10. Agent 中立运行框架

当前 `main` 新增轻量 Pipeline Runner，把已有采集、入库、文本处理、需求事件、聚类/新词、查询评分和内容洞察接为一条框架主流程。框架不依赖 Codex、OpenClaw、Hermes 或任何具体大模型 API；任意 Agent 只要能调用 Shell 或 HTTP，就能读取状态、启动一轮流程、查看结果并恢复失败运行。

核心入口：

```bash
python -m apps.cli --json status
python -m apps.cli --json run-cycle --query-id 12 --collection-limit 20
python -m apps.cli --json run-cycle --all-enabled --skip-analysis
python -m apps.cli --json run-status 1
python -m apps.cli --json retry-run 1
python -m apps.cli --json insights --latest
```

REST 入口：

- `GET /ops/api/runtime/status`
- `POST /ops/api/pipeline/runs`
- `GET /ops/api/pipeline/runs/{run_id}`
- `POST /ops/api/pipeline/runs/{run_id}/retry`
- `POST /ops/api/pipeline/runs/{run_id}/cancel`
- `GET /ops/api/insights/latest`

运行状态持久化在 `pipeline_runs`，包含 `status`、`request_data`、`progress_data`、`result_data`、`started_at`、`finished_at`、`error_message` 和可选 `idempotency_key`。详细接口见 `docs/AGENT_INTERFACE.md`，本次真实调用链审计与验证状态见 `docs/V15_AGENT_NEUTRAL_RUNTIME_REPORT.md`。

### 增量分析范围

Pipeline Runner 的分析阶段不再每轮重算全库。采集阶段会形成本轮 `PipelineScope`，只把本轮新增或文本发生变化的内容/评论送入文本处理、需求识别、候选词和洞察生成。

处理状态记录在 `analysis_processing_states`：

- `entity_type`
- `entity_id`
- `analysis_version`
- `source_updated_at`
- `source_fingerprint`
- `processed_at`
- `last_pipeline_run_id`

判断是否需要重新分析：

```text
从未处理
或 analysis_version 变化
或文本指纹变化
```

聚类和候选词发现会结合有限历史上下文，而不是全库上下文。当前上限：

```text
MAX_HISTORY_CONTEXT_PER_QUERY = 50
```

第二轮无新增/更新数据时，`processing.records_in_scope` 和 `processing.processed_records` 为 `0`，并返回 warning，不重新处理历史文本。

2026-07-02 本机 PostgreSQL 和小红书真实采集已验证：

- `alembic upgrade head` 成功，当前 revision：`0004_worker_heartbeats`
- `python -m scripts.check_runtime` 成功
- `POSTGRES_TEST_DATABASE_URL=... pytest -m postgres -q` 成功，结果：`1 passed`
- `/ops` 和 `GET /dashboard/summary` 可读取真实 PostgreSQL
- MediaCrawler 持久登录态已创建并复用
- 真实 live PostgreSQL 当前已有：114 内容、309 评论、403 用户、121 发现关系、118 快照

真实闭环剩余未通过：

- Docker 未安装，本机使用 Homebrew PostgreSQL
- 飞书 Open Platform 应用身份仍可能缺少 Base 权限；当前真实 Base 写入已通过本机 `lark-cli` 用户身份验证
- 长期无人值守运行尚未完成

在真实闭环通过前，不应把项目状态写成 100% 完成，也不应继续开发第二平台。

## 11. 本机可视化看板启动方式

2026-07-03 已补充一个面向非技术用户的本机启动入口：

```text
~/Desktop/打开AIXHS看板.command
```

双击该图标会执行 `scripts/open_dashboard.command`，自动完成以下动作：

- 进入项目目录
- 默认设置 `WORKER_ADAPTER=mediacrawler`
- 默认设置本机 Ops 控制口令 `OPS_TOKEN=secret`
- 检查 `third_party/MediaCrawler/.venv`
- 如缺少 MediaCrawler 虚拟环境，自动创建并安装 `third_party/MediaCrawler/requirements.txt`
- 检查小红书持久登录目录
- 如未检测到登录态，启动 `python -m scripts.mediacrawler_login` 引导扫码登录
- 登录完成后继续启动 API 服务
- 自动打开 `/ops` 中文看板网页

看板地址：

```text
http://127.0.0.1:8000/ops
```

页面右上角的 `OPS_TOKEN` 用于保护本机运维接口。默认本机启动器使用：

```text
secret
```

看板已改为中文显示，包含运行状态、查询、运行记录、洞察和启动一轮流程等入口。点击“启动一轮”时，如果当前没有启用查询，接口会自动创建一个默认真实查询，不再默认使用 mock 模拟采集。当前默认查询词为：

```text
KET PET 二刷
```

注意：

- `mock` 只用于自动测试或显式调试，不是当前桌面看板的默认采集模式。
- MediaCrawler 是项目内置主采集器，源码位于 `third_party/MediaCrawler`。
- `.venv` 是 MediaCrawler 的本机运行环境，不提交到 Git；缺少时启动器会自动安装。
- 首次扫码登录后，需要在终端按回车继续启动主程序。
- 真实小红书平台可能出现验证码、限流或页面变更，出现时不能伪造成功，应在看板或日志中记录失败原因。

## 12. 2026-07-06 飞书工作台变更摘要

当前主线已推送到 GitHub：

```text
https://github.com/xiaohao300000000-cmd/aixhs666/tree/main
```

主要变化：

- 新增 `FEISHU_BITABLE_TRANSPORT=lark_cli`，使用本机 `lark-cli` 用户身份写飞书 Base。
- 创建 `AI筛选客户线索` 和 `AI筛选证据明细` 两张多维表格。
- 将现有抓取数据先过规则型 AI 初筛，再写入飞书；当前 71 个客户、72 条证据。
- 新增 `python -m apps.cli --json feishu-ai-review-sync`，后续 DeepSeek 新结果可增量进入这两张飞书表。
- 新增待人工确认卡片视图，让人工优先看 `需求摘要`。
- 新增 `系统控制台` 表，普通用户可通过 `我要做什么`、`开始执行`、`现在状态` 发出一次性指令。
- 新增 `python -m apps.cli --json run-control-panel-once`，只检查一次控制台，不后台自动跑。
- 已真实验证：`开始执行=否` 时不执行；改成 `是，开始` 后执行一次并写回结果。
- 当前全量测试：`305 passed, 4 skipped, 1 warning`。
- 当前 LLM/飞书可靠性链路使用 `screening` 和 `sending` 领取态；`send_uncertain` 用于暴露不能自动重发的不确定发送结果。
- 当前跟进话术审批卡已改为“审批入库”和“真实小红书发送”分离，飞书按钮不再直接触发小红书浏览器发送。

仍未完成或尚未充分验证：

- `AI筛选客户线索` 的主字段仍是 `客户`，卡片标题还不够适合普通人阅读。
- `feishu-ai-review-sync` 已做成正式增量命令；它仍需要由本机命令、控制台动作或后续 worker 显式触发，不是后台常驻自动循环。
- AI 筛选仍是规则型，61 条待人工确认里需要人工审核和后续大模型二次评分。
- 小红书真实私信发送因本机浏览器/网络环境问题暂时搁置；不要在未解决前恢复“飞书回调里直接发送”的实现。
- 长期无人值守运行仍未完成。

## 13. 2026-07-03 变更摘要

2026-07-03 在 `feat/v15-agent-neutral-runtime` 分支完成并推送的主要变更：

- 增加 Agent 中立 Pipeline Runner，CLI 和 REST 共用同一服务层。
- 增加 `pipeline_runs` 运行状态持久化。
- 增加增量分析范围，避免每次 `run-cycle` 重算整个数据库。
- 增加 `analysis_processing_states`，用文本指纹和 `analysis_version` 判断是否需要重新分析。
- 增加有限历史上下文上限，当前每个查询最多补充 50 条历史文本。
- 增加 `/ops` 可视化看板。
- 增加桌面双击启动脚本 `scripts/open_dashboard.command`。
- 看板界面和运行反馈改为中文。
- “启动一轮”无查询时会自动创建默认真实查询。
- 桌面启动器默认使用真实 MediaCrawler 采集，不再默认 mock。
- 桌面启动器会自动检查并安装 MediaCrawler `.venv`。
- 桌面启动器会在没有小红书持久登录态时引导扫码登录，并在扫码完成后继续启动主程序和网页。

本节记录的是 2026-07-03 当日已完成事项，具体提交以 `git log` 和 GitHub 分支历史为准。

仍未完成或尚未充分验证：

- 真实小红书小规模 Pipeline Runner 全链路需要再次从看板按钮触发确认。
- 当日真实飞书凭证、真实发送和真实回调仍未验收；2026-07-06 已通过本机 `lark-cli` 用户身份验证飞书 Base 建表、写入、更新和视图创建。
- 长期无人值守运行仍未完成。
- 桌面启动器目前面向 macOS 本机；Windows/Linux 启动入口尚未制作。
