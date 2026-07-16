# V19-03 Skill Run 人类报告与每日审核队列验收报告

日期：2026-07-16

## 结论

V19-03 已在独立分支 `codex/v19-03-run-report-queue` 完成。PostgreSQL 继续作为唯一事实源；完成的 Skill Run 会保留原始 summary、checkpoint 和事件，同时生成可钻取的人类业务报告。真实全库未审核 backlog 已按高召回规则生成 Asia/Shanghai 业务日的稳定 50 条审核队列，未把 Run #8 的候选范围误当作全局队列范围。

真实验收只执行了 PostgreSQL `0019_review_queue` 迁移、Run #8 业务报告写入和当天审核队列写入。没有调用 DeepSeek、飞书写入、Base 写入、小红书采集/发送、评论发送、私信、回复检查或任何调度。

## 交付范围

- `SkillRun.business_report_json` 独立保存人类业务报告，不覆盖原始运行事实。
- `ReviewQueueItem` 保存业务日、稳定候选键、代表 Screening/Lead/Profile、来源 Run、来源 Screening 集、分层、槽位、优先级、位置、状态、紧急标记、原因、人工决定和审计时间。
- 同业务日同候选唯一；按 `(queue_date, status, position)` 建读取索引。
- 分层为 `priority_review`、`standard_review`、`uncertain_review`、`automatic_exclusion`；软不确定信号不会单独触发自动排除。
- 同 profile 的多条 Screening 合并为一个候选；无 profile 时使用来源实体稳定键。
- 默认队列严格保留 5 个 QC 位和 45 个业务位；候选 backlog 不删除；支持继续审核、只看高优先级和显式 emergency。
- 当天已有不足预算的稳定队列时，后续 Run/新候选只追加空位，不改变旧 item ID 或 position；相同输入重跑 `created=0`。
- 正常 Skill Run `summarize` 与历史 rebuild 使用同一报告和全局队列服务。
- `promote/defer/reject` 成功后，匹配的 pending 队列位置幂等转为 completed；进度从持久事实计算。
- Operator API 提供报告、按层候选、准备队列、队列/进度和继续审核能力；写接口要求非空幂等键。
- 飞书任务完成卡和结果卡读取同一业务报告摘要；自动化只生成卡片，没有发送消息。

## TDD 证据

实现过程按行为先观察失败，再做最小实现：

- 模型导入和 `0019` 迁移结构测试先失败，再增加业务报告列和队列事实。
- 报告模块缺失、软信号误排除、单个坏候选中断整批等测试先失败，再实现高召回分类、候选合并、稳定排序和可见错误隔离。
- 队列模块缺失、Asia/Shanghai 业务日、5+45 配额、超过 30 个高优先级、QC 回填、backlog、继续 20、emergency 和幂等测试先失败，再实现队列服务。
- 人工动作后队列仍 pending 的测试先失败，再把进度更新接入统一客户推进事务；重复动作不会重复增加完成数。
- Operator 服务/API、认证网关、飞书业务卡和正常 `execute_skill_run` summarize 报告/队列测试先失败，再接入同一服务。
- 过程审查发现“当天已有任意 item 就直接返回”会让不足 50 的队列永远无法补满；新增测试先得到 `created=0`（预期追加 40），再改为保留旧 ID/position 并从后续 Run 追加空位。测试同时锁定重复候选不入队和相同输入再次 `created=0`。

## 自动化验证

简报指定测试：

```text
/Users/xiaohao30000/aixhs666/.venv/bin/pytest tests/test_skill_run_report.py tests/test_daily_review_queue.py tests/test_skill_runtime.py tests/test_operator_tasks.py tests/test_operator_leads.py tests/test_customer_progression.py tests/test_feishu_task_center.py tests/test_feishu_skill_run_sync.py tests/test_operator_api.py tests/test_operator_gateway.py -q
53 passed, 1 warning in 1.06s
```

全量回归：

```text
/Users/xiaohao30000/aixhs666/.venv/bin/pytest -q
582 passed, 7 skipped, 1 warning in 28.61s
```

唯一 warning 为既有 FastAPI TestClient/httpx2 弃用提示，本任务没有新增依赖。

## 真实 PostgreSQL 写前快照

在执行迁移和服务写入前，使用主运行目录真实环境变量只读保存：

| 事实 | 写前值 |
|---|---:|
| Alembic revision | `0018_customer_crm` |
| `review_queue_items` | 不存在 |
| `skill_runs.business_report_json` | 不存在 |
| Screening 总数 | 100 |
| 未人工审核 Screening | 86 |
| 已人工审核 Screening | 14 |
| 不同未审核候选键 | 86 |
| Run #8 状态 | `succeeded` |
| Run #8 checkpoint Screening | 50 |
| Run #8 原始 summary | 存在 |
| Run #8 事件 | 57 |
| Lead CRM 阶段 | candidate 57、invalid 6、new_customer 12 |

现场有 86 个不同未审核候选，因此可以真实声明默认队列为 50；没有制造候选补数。

## 迁移

```text
Running upgrade 0018_customer_crm -> 0019_review_queue
0019_review_queue (head)
```

迁移在 PostgreSQL 事务 DDL 下成功完成，新增列、事实表、唯一约束和读取索引均来自新 `0019`，没有修改任何既有迁移。

## 真实分类与默认全局队列

迁移后、建队列前只读分类全库未审核事实：

| 分层 | 候选数 |
|---|---:|
| 高优先级 | 1 |
| 普通 | 0 |
| 不确定 | 78 |
| 明确自动排除 | 7 |
| 合计 | 86 |

分类错误为 0；现场没有同 profile 的多 Screening 候选，因此真实 `multi_screening_candidates=0`，同 profile 合并由自动化 fixture 证明。

业务日 `2026-07-16` 的持久队列：

| 队列事实 | 值 |
|---|---:|
| 总数 | 50 |
| QC | 5 |
| 业务位 | 45 |
| 高优先级 | 1 |
| 不确定 | 49 |
| emergency | 0 |
| pending/completed | 50 / 0 |
| 剩余 backlog | 36 |
| 重复 candidate_key | 0 |

真实软不确定候选进入队列 49 个，证明低信号没有被直接丢弃。由于不确定候选足够，5 个 QC 位全部按第一顺序取自不确定候选，未使用自动排除抽检回填。第 51 条以后的 36 个候选仍保留在 Screening/backlog 中，没有删除或篡改。

队列来源 Run 分布为 Run #14 23 个、Run #15 6 个、无法由现有 succeeded checkpoint 反查的历史候选 21 个。这证明默认队列使用全库真实未审核 backlog，而不是限定 Run #8。

## Run #8 报告与全局队列的区分

Run #8 报告只对 checkpoint 内的 50 条真实 Screening 建候选明细：

```text
本次分析 50 条公开内容，合并得到 49 个待审核候选，其中 1 个为高优先级。
```

Run #8 明细分层：高优先级 1、普通 0、不确定 48、明确自动排除 1；`candidate_count=50`，可审核候选为 49。主动作是“审核本次候选”，深链 `/leads?run_id=8`。

同一报告的队列字段明确写为：

```json
{
  "scope": "global_unreviewed_backlog",
  "prepared": 50,
  "quality_control": 5,
  "emergency": 0,
  "backlog": 36,
  "errors": []
}
```

因此 Run #8 专属候选入口和全局日队列没有混为一谈，也没有因 Run #8 只有 49 个可审核候选而错误宣称全局不足 50。

## 幂等与审计事实保留

首次真实准备前队列表为空，执行服务后持久事实为 50 条。随后以相同业务日、Run 和幂等键连续准备两次：

- 两次均 `created=0`、`total=50`、`quality_control=5`、`backlog=36`；
- 初始持久队列、第一次重复、第二次重复的 item ID、candidate_key 和 position 完全相同；
- 50 个 candidate_key 全部唯一；
- 两次 Run 报告结构完全相同；
- 原始 summary 哈希、checkpoint 哈希、Run #8 事件数、Screening 100/86/14 计数和 Lead CRM 阶段分布前后完全相同。

原始事实哈希：

```text
result_summary_json sha256: 12371e1b6b3626f7adff6040bc7187260810322659b215de3866495faf872cf4
checkpoint_json sha256:     fce87577b1f65e9f51613e9120c97893e6774db46e65757fb299925cfca94189
Skill Run #8 events:         57 -> 57
Screening counts:            100/86/14 -> 100/86/14
```

第一次真实验收命令在两个服务调用和 `commit` 成功后，因输出脚本错误引用不存在的展示键 `business` 而报 `KeyError`。只读核对确认已持久化 50 条队列和 1 份 Run 报告；未删除或重建这些事实，而是在其上追加上述两次 `created=0` 复验。该错误只影响终端输出，不影响业务事务。

## 真实 Operator API 读取

使用只挂载受 token 保护 Operator router 的本地 Gateway TestClient，连接真实 PostgreSQL，只执行 GET：

| 请求 | 结果 |
|---|---:|
| 无 token 读取 Run 报告 | HTTP 401 |
| 有 token 读取 Run #8 报告 | HTTP 200 |
| 有 token读取 Run #8 分层候选 | HTTP 200，50 个 |
| 有 token 读取 2026-07-16 全局队列 | HTTP 200，50 个 |

队列响应直接返回进度 `completed=0,target=50,pending=50,quality_control=5`，以及稳定候选键、Run/Lead/Screening、分层、原因、位置、状态、妙搭相对深链和下一步。操作者不需要理解原始 JSON。

## 非触发证明

- 真实验收代码路径只导入数据库、报告、队列、Operator 读取服务。
- 没有传入 LLM client，也没有调用正常 Skill Run 执行、调度或采集入口。
- 没有调用飞书卡片发送、Base 同步、公开回复、私信、回复检查或任何小红书接口。
- 没有发布妙搭，没有推送、合并或创建 PR。

## 已知风险

- 现场 86 个候选恰好都是单 Screening 候选；同 profile 多证据合并的真实数据证据当前不存在，自动化已覆盖该规则。
- 21 个队列项无法从现存 succeeded Run checkpoint 反查来源 Run，`source_run_id` 如实为空；候选仍由 Screening 事实完整追踪。
- 写 API 强制非空幂等键，但没有新增请求级幂等账本；实体幂等依赖数据库唯一约束和稳定候选键。
- 未配置妙搭公网 URL 时深链为相对路径；页面和连续审核体验属于 V19-04。
- FastAPI TestClient 有既有 httpx2 弃用 warning，不影响当前行为。

## 提交

```text
309f92a feat: add daily review queue facts
c15ae2b feat: build human Skill Run reports
253383e feat: plan high-recall daily reviews
f82d4e5 feat: expose review queue operator APIs
docs: verify V19-03 run report queue
```
