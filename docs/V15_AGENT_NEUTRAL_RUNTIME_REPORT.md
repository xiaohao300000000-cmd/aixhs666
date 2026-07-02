# V15 Agent 中立运行框架报告

日期：2026-07-03

## 真实旧流程审计

1. 一次真实搜索运行由 `collection_tasks` 和 `apps.worker.main.WorkerRunner` 推进。`search` 任务只调用 `run_search_task` 和 `ingest_search_results`，不会自动调用详情、评论、文本处理、聚类、评分或洞察。
2. `MediaCrawlerXiaohongshuAdapter.search()` 一次平台 search 会读取 `search_contents_*.jsonl` 和 `search_comments_*.jsonl`，并把详情和评论缓存到 adapter 内。后续 `get_content()`、`list_comments()` 可复用缓存，不需要再次访问小红书。
3. 搜索入库路径是 `run_search_task -> ingest_search_results -> ingest_content + upsert_discovery_relation`。详情入库路径是独立 `run_detail_task -> ingest_profile + ingest_content`。评论入库路径是独立 `run_comment_task -> ingest_comment`，评论作者会通过 profile identity 写入/更新。
4. T14 文本处理存在于 `intelligence/text_processing`，旧主搜索流程不会自动调用。
5. T15 聚类和新词发现存在于 `intelligence/clustering` 和 `intelligence/phrase_discovery`，旧主搜索流程不会自动调用。
6. T13 查询评分存在于 `intelligence/scoring`，旧采集后不会自动更新。
7. T18 需求事件链存在于 `intelligence/demand_chain`，旧采集后不会根据真实内容自动生成。
8. T21 内容洞察存在于 `intelligence/content_insights`，旧采集后不会自动输出。
9. T13-T21 多数模块有独立函数和测试，但没有进入一次真实 search 任务后的运行闭环。
10. 当前真实采集任务主要由项目框架的 worker/task 表推进；但完整“采集后分析闭环”此前依赖验证脚本或人工/Agent 临时逐步调用，不是框架内固定流程。

## 新运行链路

新增 `services/pipeline_runner.py`：

```text
选择查询
→ 创建并执行 search task
→ 对本轮发现内容执行 detail task
→ 对本轮发现内容执行 comment task
→ 文本处理与低信息统计
→ 需求事件链生成
→ 语义聚类与候选新词发现
→ 查询评分
→ 内容洞察
→ pipeline_runs.result_data
```

REST 和 CLI 都调用同一个 `PipelineRunner` 服务层。

## 增量分析修正

旧实现中 `_text_records(session)` 会读取全部 `contents` 和全部 `comments`，导致每次 `run-cycle` 都重算历史文本、历史需求事件、历史聚类和历史候选词。

当前实现改为：

```text
本轮新增/更新内容和评论
→ 增量文本处理
→ 增量需求识别
→ 本轮文本 + 有限历史上下文做聚类/候选词/洞察
```

新增 `PipelineScope` 记录本轮范围：

- `query_ids`
- `content_ids`
- `new_content_ids`
- `updated_content_ids`
- `comment_ids`
- `new_comment_ids`
- `updated_comment_ids`
- `profile_ids`

新增表 `analysis_processing_states`，记录：

- `entity_type`
- `entity_id`
- `analysis_version`
- `source_updated_at`
- `source_fingerprint`
- `processed_at`
- `last_pipeline_run_id`

判断是否需要重新处理：

```text
从未处理
或 analysis_version 变化
或 source_fingerprint 变化
```

为避免重复采集刷新 `updated_at` 导致误判，当前 `source_fingerprint` 只基于影响分析的文本字段：

- 内容：`title + body_text`
- 评论：`body_text + parent_comment_id`

历史上下文上限：

```text
MAX_HISTORY_CONTEXT_PER_QUERY = 50
```

无新增/更新文本时，分析阶段正常完成，`records_in_scope=0`，不再重跑全库，并返回 warning。

## pipeline_runs 状态设计

表：`pipeline_runs`

字段：

- `id`
- `status`: `pending`、`running`、`partial`、`completed`、`failed`、`cancelled`
- `requested_by`
- `request_data`
- `progress_data`
- `result_data`
- `started_at`
- `finished_at`
- `error_message`
- `idempotency_key`

`progress_data` 记录阶段：`collection`、`processing`、`demand_events`、`clustering`、`query_scoring`、`insight`。

## 已接入主流程

- 搜索采集：已接入。
- 详情入库：已接入。
- 评论入库：已接入。
- 用户入库：已接入。
- 文本处理：已接入。
- 需求事件链：已接入。
- 聚类和新词发现：已接入。
- 查询评分：已接入。
- 内容洞察：已接入。
- 运行状态持久化：已接入。
- CLI 和 REST 标准接口：已接入。

## 自动测试

已新增 `tests/test_pipeline_runner.py`，覆盖：

- Mock 完整闭环：只调用一次 Pipeline Runner，自动完成采集、入库、处理、事件、聚类/新词、评分、洞察和 run 状态。
- 幂等：同一查询连续运行两次不重复内容、评论和发现关系。
- 失败恢复：模拟 clustering 阶段失败，保留已完成采集与进度，retry 后完成且不重复数据。
- API/CLI：REST 和 CLI 使用同一服务结构，JSON 状态可查询。

本机结果：

```text
.venv/bin/python -m pytest -q
169 passed, 2 skipped, 1 warning

.venv/bin/python -m pytest -m postgres -q
1 skipped, 170 deselected, 1 warning
```

PostgreSQL 标记测试因当前环境没有启用对应真实测试数据库而 skipped。

增量分析新增测试结果：

- 第二轮无新数据：`records_in_scope == 0`，不重新处理旧内容/评论。
- 只新增一条评论：`records_in_scope == 1`。
- 内容正文变化：只重新处理该内容，旧评论不处理。
- 分析版本从 v1 改 v2：本轮范围内旧数据重新进入处理范围。
- 聚类失败：不写入处理状态，retry 后重新处理对应范围。
- 1000 内容 + 3000 评论历史数据：本轮新增 1 内容 + 2 评论时，`records_in_scope == 3`，`historical_context_records <= 50`，`total_records_used <= 53`。

## 真实数据验证

尚未完成真实小红书 Pipeline Runner 小规模验证。

当前最新副本中未发现：

- `third_party/MediaCrawler/.venv/bin/python`
- 可见的 MediaCrawler 持久登录态目录

因此没有伪造真实运行成功。真实验证需要先安装 MediaCrawler 依赖并确认登录态：

```bash
python3.12 -m venv third_party/MediaCrawler/.venv
third_party/MediaCrawler/.venv/bin/pip install -r third_party/MediaCrawler/requirements.txt
python -m scripts.mediacrawler_login
```

验证命令：

```bash
python -m apps.cli --json run-cycle --query-id <真实查询ID> --collection-limit 5
python -m apps.cli --json run-status <run_id>
python -m apps.cli --json insights --latest
```

真实验证需记录：输入查询、新增内容、新增评论、新增用户、处理内容数、低信息数、需求事件数、聚类/候选词数、更新评分数、最终洞察、失败和警告。

## 尚未验证

- 真实小红书 Pipeline Runner 小规模闭环。
- 真实 PostgreSQL 上新增 `0005_pipeline_runs` migration。
- 真实飞书发送与回调。
- 4-8 小时长期运行。

## Agent 调用方式

Codex：调用 `python -m apps.cli --json ...` 或 REST。

OpenClaw：通过 Shell 或 HTTP 工具调用同一接口。

Hermes：通过 Shell、HTTP 或未来 MCP 包装调用同一服务；无需依赖 Codex 会话记忆。
