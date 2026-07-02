# AI 教育需求发现与获客效率系统

## 1. 项目简介

本项目用于从小红书等公开平台持续发现教育相关需求，采集帖子、评论、回复和公开主页信息，建立可追溯的数据资产，并逐步提升获客效率。

项目第一阶段不追求自动销售，而是先解决四件事：

1. 稳定获得足够多的公开需求数据
2. 保存完整上下文和发现路径
3. 自动发现新的搜索词、需求场景和高价值来源
4. 对少量高价值信号进行人工预警和验证

长期目标是形成一套可迁移到装修、留学、移民、本地生活等行业的“公开市场需求感知引擎”。

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
- 自动评论
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
163 passed, 2 skipped, 1 warning
```

主采集后端固定为 MediaCrawler：

```bash
python -m apps.worker --once
```

默认 `WORKER_ADAPTER=mediacrawler`。该后端通过 `MEDIACRAWLER_HOME` 指向项目内 `third_party/MediaCrawler`，运行其小红书 search 模式并读取 JSONL 输出。MediaCrawler 一次 search 会同时补详情和评论，适配层会缓存这些输出，后续 detail/comment 任务优先复用缓存。

登录态固化方式：

- 默认 `MEDIACRAWLER_ENABLE_CDP_MODE=true`
- 默认 `MEDIACRAWLER_CDP_CONNECT_EXISTING=false`
- 默认 `MEDIACRAWLER_SAVE_LOGIN_STATE=true`
- 默认 `MEDIACRAWLER_AUTO_CLOSE_BROWSER=false`
- 默认持久 profile：`third_party/MediaCrawler/browser_data/cdp_aixhs_xhs_user_data_dir`

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

## 9. Agent 中立运行框架

当前分支新增轻量 Pipeline Runner，把已有采集、入库、文本处理、需求事件、聚类/新词、查询评分和内容洞察接为一条框架主流程。框架不依赖 Codex、OpenClaw、Hermes 或任何具体大模型 API；任意 Agent 只要能调用 Shell 或 HTTP，就能读取状态、启动一轮流程、查看结果并恢复失败运行。

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

2026-07-02 本机 PostgreSQL 和小红书真实采集已验证：

- `alembic upgrade head` 成功，当前 revision：`0004_worker_heartbeats`
- `python -m scripts.check_runtime` 成功
- `POSTGRES_TEST_DATABASE_URL=... pytest -m postgres -q` 成功，结果：`1 passed`
- `/ops` 和 `GET /dashboard/summary` 可读取真实 PostgreSQL
- MediaCrawler 持久登录态已创建并复用
- 真实 live PostgreSQL 当前已有：114 内容、309 评论、403 用户、121 发现关系、118 快照

真实闭环剩余未通过：

- Docker 未安装，本机使用 Homebrew PostgreSQL
- 真实飞书凭证未配置，仅完成 dry-run 和 mocked HTTP 测试
- 长期无人值守运行尚未完成

在真实闭环通过前，不应把项目状态写成 100% 完成，也不应继续开发第二平台。
