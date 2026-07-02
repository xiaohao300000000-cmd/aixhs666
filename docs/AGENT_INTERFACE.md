# Agent 中立运行接口

本项目的运行框架不绑定 Codex、OpenClaw、Hermes 或具体大模型供应商。Agent 只需要 Shell 或 HTTP 能力，就可以读取系统状态、启动一轮采集分析、调整策略并获取结构化结果。

## 能力列表

- 获取当前系统状态：活跃查询数、内容数、评论数、用户数、最近 pipeline run。
- 获取启用查询及评分：复用 `/ops/api/queries` 和 Pipeline 结果里的 `query_scores`。
- 启动一轮完整流程：搜索、详情、评论、用户入库、文本处理、需求事件、聚类/新词、查询评分、洞察。
- 指定 `query_id`、运行全部启用查询、设置采集数量、跳过分析、dry-run。
- 查询运行状态和每阶段进度。
- 失败后 retry，并保留已完成采集数据。
- 查看候选新词和最新内容洞察。
- 通过既有查询 API 调整启停状态和优先级。

## CLI

统一入口：

```bash
python -m apps.cli --json status
python -m apps.cli --json run-cycle --query-id 12 --collection-limit 20
python -m apps.cli --json run-cycle --all-enabled --skip-analysis
python -m apps.cli --json run-cycle --all-enabled --dry-run
python -m apps.cli --json run-status 123
python -m apps.cli --json retry-run 123
python -m apps.cli --json insights --latest
```

所有命令支持 `--json`。没有 `--json` 时也输出可读 JSON 摘要。

## REST

写操作仍使用 Ops Token：

```bash
curl -H "X-Ops-Token: $OPS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query_ids":[12],"collection_limit":20,"requested_by":"agent"}' \
  http://localhost:8000/ops/api/pipeline/runs
```

接口：

- `GET /ops/api/runtime/status`
- `POST /ops/api/pipeline/runs`
- `GET /ops/api/pipeline/runs/{run_id}`
- `POST /ops/api/pipeline/runs/{run_id}/retry`
- `POST /ops/api/pipeline/runs/{run_id}/cancel`
- `GET /ops/api/insights/latest`

请求体：

```json
{
  "query_ids": [12],
  "all_enabled": false,
  "collection_limit": 20,
  "skip_analysis": false,
  "dry_run": false,
  "requested_by": "agent",
  "idempotency_key": "optional-agent-key"
}
```

## 返回结构

`result_data` 使用稳定字段：

```json
{
  "run_id": 123,
  "status": "completed",
  "started_at": "2026-07-03T00:00:00+00:00",
  "finished_at": "2026-07-03T00:01:00+00:00",
  "queries": {"requested": 1, "completed": 1, "failed": 0},
  "collection": {
    "contents_found": 20,
    "new_contents": 12,
    "existing_contents": 8,
    "new_comments": 36,
    "new_profiles": 24,
    "duplicates": 8
  },
  "processing": {
    "processed_contents": 56,
    "low_information_contents": 7,
    "demand_events_created": 15
  },
  "intelligence": {
    "clusters_created_or_updated": 6,
    "candidate_queries_created": 4,
    "query_scores_updated": 8
  },
  "warnings": [],
  "errors": [],
  "recommended_actions": []
}
```

完整 `GET /ops/api/pipeline/runs/{run_id}` 还包含：

- `request_data`
- `progress_data`
- `error_message`
- `idempotency_key`

`progress_data` 示例：

```json
{
  "collection": "completed",
  "processing": "completed",
  "demand_events": "completed",
  "clustering": "completed",
  "query_scoring": "completed",
  "insight": "completed"
}
```

## 推荐 Agent 工作流程

1. 调用 `status` 或 `GET /ops/api/runtime/status`。
2. 调用 `/ops/api/queries` 查看活跃查询、优先级和历史产出。
3. 选择一个或多个查询，调用 `run-cycle` 或 `POST /pipeline/runs`。
4. 读取 `result_data.collection` 判断采集质量。
5. 读取 `result_data.insight.candidate_queries` 和 `recommended_actions`。
6. 使用既有 `/ops/api/queries/{query_id}/priority`、`enable`、`disable` 调整策略。
7. 对失败运行调用 `retry-run` 或 `POST /pipeline/runs/{run_id}/retry`。

## 错误处理

- 无查询：返回清晰错误，不创建伪成功。
- 阶段失败：`pipeline_runs.status=failed`，`progress_data` 保留已完成/失败前阶段，`error_message` 写入错误。
- 采集局部失败：单查询失败会进入 `errors`，其他查询继续；最终可能为 `partial`。
- 平台受限：错误或警告会写入 `warnings`/`errors`，Agent 不需要解析日志。

## 幂等说明

- 内容、评论、用户和发现关系沿用现有唯一约束和 upsert，重复运行不会重复入库。
- 每次 `run-cycle` 默认创建独立 `pipeline_runs` 记录。
- 提供 `idempotency_key` 时，已完成的同 key 运行会直接返回既有记录。

## 失败恢复

失败后：

```bash
python -m apps.cli --json run-status 123
python -m apps.cli --json retry-run 123
```

retry 会复用原始 `request_data` 并写回同一个 `pipeline_runs.id`。已完成的采集数据不会回滚丢失，重新运行依靠唯一约束避免重复内容、评论和发现关系。

## 适配示例

Codex：优先使用 CLI；需要 Web 服务时使用 REST。

OpenClaw：通过 Shell 工具执行 `python -m apps.cli --json ...`，或通过 HTTP 工具调用 `/ops/api`。

Hermes：通过 Shell、HTTP，或未来把同一服务函数包装成 MCP 工具；不需要修改 Pipeline Runner。
