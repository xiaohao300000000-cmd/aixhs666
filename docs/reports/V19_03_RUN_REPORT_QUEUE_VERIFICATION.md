# V19-03 Skill Run 人类报告与每日审核队列验收报告

日期：2026-07-16

## 结论

V19-03 已在独立分支 `codex/v19-03-run-report-queue` 完成。PostgreSQL 继续作为唯一事实源；完成的 Skill Run 会保留原始 summary、checkpoint 和事件，同时生成可钻取的人类业务报告。真实全库未审核 backlog 已按高召回规则生成 Asia/Shanghai 业务日的稳定 50 条审核队列，未把 Run #8 的候选范围误当作全局队列范围。第三轮主控返工新增持久请求幂等事实，report rebuild、prepare queue 和 continue queue 现在会重放首次稳定结果，而不只是依赖候选唯一性。

初次真实验收只执行了 PostgreSQL `0019_review_queue` 迁移、Run #8 业务报告写入和当天审核队列写入。第三轮返工先保存只读快照，再只执行新增 `0020_review_queue_idempotency` schema migration；没有在真实库调用 report rebuild、prepare 或 continue。全过程没有调用 DeepSeek、飞书写入、Base 写入、小红书采集/发送、评论发送、私信、回复检查或任何调度。

## 交付范围

- `SkillRun.business_report_json` 独立保存人类业务报告，不覆盖原始运行事实。
- `ReviewQueueItem` 保存业务日、稳定候选键、代表 Screening/Lead/Profile、来源 Run、来源 Screening 集、分层、槽位、优先级、位置、状态、紧急标记、原因、人工决定和审计时间。
- 同业务日同候选唯一；按 `(queue_date, status, position)` 建读取索引。
- 分层为 `priority_review`、`standard_review`、`uncertain_review`、`automatic_exclusion`；软不确定信号不会单独触发自动排除。
- 同 profile 的多条 Screening 合并为一个候选；无 profile 时使用来源实体稳定键。
- 跨候选排序显式使用分层、意向、置信度、候选最新更新时间、代表 Screening 稳定 ID 和 candidate key；更新时间输出为 UTC ISO 字符串。
- 候选资格按稳定候选键判断：同 profile 只要任一 Screening 已人工审核，未来全局或 Run 队列都不再把该 profile 作为 pending；无 profile 仅排除完全相同的来源键。
- 默认队列严格保留 5 个 QC 位和 45 个业务位；候选 backlog 不删除；支持继续审核、只看高优先级和显式 emergency。
- 当天已有不足预算的稳定队列时，后续 Run/新候选只追加空位，不改变旧 item ID 或 position；相同输入重跑 `created=0`。
- 正常 Skill Run `summarize` 与历史 rebuild 使用同一报告和全局队列服务。
- `promote/defer/reject` 成功后，匹配的 pending 队列位置幂等转为 completed；进度从持久事实计算。
- `ReviewQueueOperation` 持久保存操作域、业务日、SHA-256 key hash、规范请求、首次稳定结果和审计时间；全局唯一 hash 同时阻止跨操作域或跨业务日误复用。
- Operator API 提供报告、按层候选、准备队列、队列/进度和继续审核能力；三个 V19-03 写入口均要求非空幂等键、同请求稳定重放、冲突请求返回安全 HTTP 400。
- 飞书任务完成卡和结果卡读取同一业务报告摘要；自动化只生成卡片，没有发送消息。

## TDD 证据

实现过程按行为先观察失败，再做最小实现：

- 模型导入和 `0019` 迁移结构测试先失败，再增加业务报告列和队列事实。
- 报告模块缺失、软信号误排除、单个坏候选中断整批等测试先失败，再实现高召回分类、候选合并、稳定排序和可见错误隔离。
- 队列模块缺失、Asia/Shanghai 业务日、5+45 配额、超过 30 个高优先级、QC 回填、backlog、继续 20、emergency 和幂等测试先失败，再实现队列服务。
- 人工动作后队列仍 pending 的测试先失败，再把进度更新接入统一客户推进事务；重复动作不会重复增加完成数。
- Operator 服务/API、认证网关、飞书业务卡和正常 `execute_skill_run` summarize 报告/队列测试先失败，再接入同一服务。
- 过程审查发现“当天已有任意 item 就直接返回”会让不足 50 的队列永远无法补满；新增测试先得到 `created=0`（预期追加 40），再改为保留旧 ID/position 并从后续 Run 追加空位。测试同时锁定重复候选不入队和相同输入再次 `created=0`。
- 主控验收发现原实现只过滤 `human_review_status IS NULL` 的单行：同 profile 一条已审核、另一条未审核时仍会重新入队。新增全局与 Run 两条测试先同时失败（均实际创建 2、预期 1），其中 Run checkpoint 刻意不包含已审核兄弟行；最小实现改为先建立全库已审核稳定候选键集合，再过滤当前范围。两条测试转绿，并证明无 profile 的其他来源键不被误排。
- 主控第二轮验收发现跨候选只按 `priority_rank/confidence/Screening ID/candidate_key` 排序，intent 和 candidate updated_at 没有进入完整 tie-break。新增三项排序测试：同层同 confidence 时更强 intent 必须优先；同层同 intent 同 confidence 时更新时间更新者必须优先；其余完全相同时由稳定 ID/candidate key 兜底且反转输入重复构建一致。前两项 RED 均显示旧实现错误地把 `source:comment:20` 排在 `source:comment:10` 前；加入显式排序键后 8 项报告测试全部转绿。
- 主控第三轮验收指出“要求非空 key”不等于请求幂等：旧 continue 用同一 key 连续执行 20 条时，第二次把持久队列从 20 扩到 40；同 key 改 additional、priority_only 或业务日的三项测试均未抛错；底层事实变化后同 key report rebuild 也返回了不同结论。先锁定这些 RED，再新增 `ReviewQueueOperation` 和统一重放器。GREEN 证明同键 continue 跨事务返回相同 item IDs、总数保持 20，三种参数冲突及跨操作域复用均拒绝，report 与 prepare 返回首次结果。

## 自动化验证

简报指定测试：

```text
/Users/xiaohao30000/aixhs666/.venv/bin/pytest tests/test_skill_run_report.py tests/test_daily_review_queue.py tests/test_skill_runtime.py tests/test_operator_tasks.py tests/test_operator_leads.py tests/test_customer_progression.py tests/test_feishu_task_center.py tests/test_feishu_skill_run_sync.py tests/test_operator_api.py tests/test_operator_gateway.py -q
65 passed, 1 warning in 1.25s
```

全量回归：

```text
/Users/xiaohao30000/aixhs666/.venv/bin/pytest -q
594 passed, 7 skipped, 1 warning in 27.90s
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

第三轮返工没有修改已执行的 `0019`，而是新增单向后续迁移：

```text
Running upgrade 0019_review_queue -> 0020_review_queue_idempotency
0020_review_queue_idempotency (head)
```

`0020` 只新增 `review_queue_operations`：字段为 `id`、`operation_kind`、`queue_date`、`idempotency_key_hash`、`request_json`、`result_json`、`created_at`；唯一约束为 `uq_review_queue_operations_key_hash`，审计读取索引为 `ix_review_queue_operations_kind_date_created`。真实迁移后表内记录为 0，因为本轮禁止在真实库调用三个写入口。

## 真实分类与默认全局队列

迁移后、建队列前只读分类全库未审核事实：

| 分层 | 候选数 |
|---|---:|
| 高优先级 | 1 |
| 普通 | 0 |
| 不确定 | 78 |
| 明确自动排除 | 7 |
| 合计 | 86 |

分类错误为 0；该数字是首次建队列前按未审核 Screening 行计算的原始现场快照。主控返工后的候选级只读重算见下节，未来可入队候选为 85。

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

## 主控返工：候选级已审核排除

主控验收复现了一个 Important 缺陷：V19-01 progression 只更新 latest Screening，因此同 profile 可以同时存在一条已审核 Screening 和一条 `human_review_status=null` 的旧/新 Screening。旧 `_eligible_candidates()` 只做行级 `IS NULL` 过滤，会让同一个稳定 profile 候选再次进入未来 pending 队列。

修复后的资格规则：

- 先从全库人工审核事实建立稳定 candidate key 集合；
- 有 profile 使用 `profile:{public_profile_id}`，任一兄弟 Screening 已审核即排除整个候选；
- 无 profile 使用 `source:{source_entity_type}:{source_entity_id}`，只排除完全相同来源键，不因其他已审核来源误排；
- 该规则在全局 backlog 和 `source_run_id` Run checkpoint 两条路径共用；已审核兄弟行即使不在 checkpoint 内也会生效。

真实 PostgreSQL 只读事务复验：

| 事实 | 值 |
|---|---:|
| 修复后未来可入队候选 | 85 |
| 高优先级 / 不确定 / 自动排除 | 1 / 77 / 7 |
| 分类错误 | 0 |
| 既有队列总数 / 唯一键 | 50 / 50 |
| 既有队列 QC / pending | 5 / 50 |
| 既有位置范围 | 1–50 |
| 队列签名 SHA-256 | `953d37250fec68edd5c4dc1ad72f40c9c0e8fe742fee60fd2ca0ca051176a34e` |
| 连续两次只读结果 | 完全一致 |

候选级规则比初次行级快照少 1 个未来可入队候选。现有 50 条队列中恰有 1 个键已存在候选级人工审核事实；按主控硬要求，本次没有删除、重建或修改这条既有持久事实，队列仍保持原 ID、候选键、位置和状态。新规则只阻止它在未来队列中再次被创建。

## 主控第二轮返工：完整跨候选排序

旧实现中的 `priority_rank` 只编码层级和 confidence；跨候选排序没有显式 intent，updated_at 只参与同一候选内部代表 Screening 的选择，无法表达不同候选的新鲜度。

修复后的完整排序顺序为：

```text
layer desc
→ intent rank (high > medium > low > unknown)
→ confidence desc
→ candidate latest updated_at desc
→ representative_screening_id desc
→ candidate_key asc
```

候选 `updated_at` 取聚合内最新 Screening 时间，规范为 UTC ISO 8601；它不包含个人内容或联系方式。`priority_rank` 继续作为持久队列的可解释层级/置信度事实，但不再被用来隐式代替完整排序维度。

真实 PostgreSQL 仅在 `READ ONLY` 事务中验证：修复后的 85 个未来候选连续构建两次，candidate key 顺序完全一致，所有 `updated_at` 均为稳定 ISO 字符串，分类错误为 0。没有调用 prepare/rebuild，也没有改变既有 Run 报告或队列。

既有队列只读复验仍为 50 条、5 QC、50 个唯一键、位置 1–50，签名仍是：

```text
953d37250fec68edd5c4dc1ad72f40c9c0e8fe742fee60fd2ca0ca051176a34e
```

5+45、QC 回填、高优先级无上限、backlog、继续审核和 emergency 行为由原队列回归继续锁定；排序修复只影响未来候选选择顺序，不重排当天已持久化位置。

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

## 实体稳定性与持久请求幂等

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

上述事实唯一性只能保证相同候选不重复，不能保证相同 API 请求不再选择下一批候选。第三轮返工已经关闭这个风险：

- key 先去除首尾空白，再只持久保存 SHA-256 hash；规范请求和结果均经过稳定 JSON 归一化，原始 key 不进入请求或结果事实。
- 三个操作域分别为 `report_rebuild`、`prepare_review_queue`、`continue_review_queue`，都记录 Asia/Shanghai 业务日。
- 同 hash、同操作域、同业务日、同规范请求直接返回首次 `result_json`；不会再次执行报告重建或队列选择。
- 同 hash 但 additional、priority_only、业务日、Run 或操作域不同会在任何业务写入前抛出通用冲突；HTTP 返回 400 `idempotency key conflicts with an existing operation`，响应不包含原 key 或堆栈。
- SQLite 跨 Session 回归证明 continue 20 首次和重试返回完全相同的 20 个 item IDs、`created=20`、队列总数 20；三个冲突分支和跨域复用均被拒绝。
- prepare 回归在首次结果后新增候选，重试仍返回首次 item IDs/计数且不补新候选；report 回归在首次结果后改变底层 Screening，重试仍返回首次报告。

第三轮真实 PostgreSQL 写前只读快照保存在 `/tmp/V19_03_0020_BEFORE_SNAPSHOT.json`；迁移后只读快照保存在 `/tmp/V19_03_0020_AFTER_SNAPSHOT.json`。两次均为显式 `READ ONLY` 事务并回滚：

| 事实 | 0020 前 | 0020 后 |
|---|---:|---:|
| Alembic revision | `0019_review_queue` | `0020_review_queue_idempotency` |
| 请求幂等事实表 | 不存在 | 存在，0 条 |
| 队列总数 / QC / pending | 50 / 5 / 50 | 50 / 5 / 50 |
| 唯一 candidate key | 50 | 50 |
| 位置范围 | 1–50 | 1–50 |
| 本轮队列签名 SHA-256 | `01b471b383845cc86f14f4b15f22a8cf7b6e3ab8f60f85ae30bc555fa72361f7` | 相同 |

本轮签名按 `id/candidate_key/position/slot_type/status/is_emergency` 的有序 JSON 计算，用于迁移前后对比；此前验收采用的签名仍为 `953d372…34e`，两套口径都没有发现队列变化。

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
- 主控返工的真实复验使用 PostgreSQL `READ ONLY` 事务，只读取 revision、候选资格和既有队列签名。
- 主控第二轮返工同样只在 `READ ONLY` 事务中构建候选排序并读取既有队列，没有执行报告或队列写入。
- 主控第三轮返工只在 SQLite fixture 证明请求重放；真实 PostgreSQL 只执行 `0020` schema migration 和前后 `READ ONLY` 快照，操作事实表保持 0 条，没有调用 continue、prepare 或 rebuild。

## 已知风险

- 候选级只读复验发现 86 个未审核行级候选中有 1 个 profile 已存在其他人工审核事实，因此未来合格候选为 85；既有队列按主控要求保留该持久行，不做追溯清理。
- 21 个队列项无法从现存 succeeded Run checkpoint 反查来源 Run，`source_run_id` 如实为空；候选仍由 Screening 事实完整追踪。
- 请求 key hash 采用全局唯一约束，因此同一个 key 不能跨操作域或业务日复用；调用方必须为新业务请求生成新 key。
- 未配置妙搭公网 URL 时深链为相对路径；页面和连续审核体验属于 V19-04。
- FastAPI TestClient 有既有 httpx2 弃用 warning，不影响当前行为。

## 提交

```text
309f92a feat: add daily review queue facts
c15ae2b feat: build human Skill Run reports
253383e feat: plan high-recall daily reviews
f82d4e5 feat: expose review queue operator APIs
1689e34 docs: verify V19-03 run report queue
7171133 fix: keep reviewed candidates out of review queue
f69a4ff fix: order review candidates by complete business tie-break
本报告所在提交 fix: persist review queue request idempotency
```
