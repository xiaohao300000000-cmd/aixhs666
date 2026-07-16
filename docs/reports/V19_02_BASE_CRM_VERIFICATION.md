# V19-02 Base 客户 CRM 验收报告

日期：2026-07-16

## 结论

V19-02 已在独立分支 `codex/v19-02-base-crm` 完成。PostgreSQL 继续作为唯一事实源；真实飞书 Base 已用非破坏方式扩展为客户 CRM 投影并新增一事一行的跟进记录表；五类人工字段仅通过白名单 pull 回写。真实 PostgreSQL、真实 Base 与 Operator API 已对同一客户完成一致性、幂等 upsert 和可逆回写验收。

本次没有发布妙搭，没有触发小红书采集、公开回复、私信、回复检查或调度。

## 交付范围

- 在现有 `Lead` 上增加 CRM 阶段、客户标签、最近联系时间/结果和单调同步版本。
- 新增 `CustomerFollowupRecord`，唯一 `event_key`，并按 `(lead_id, occurred_at)` 建索引。
- `promote` 在同一数据库事务中幂等创建“待首次联系”跟进事实，但不调用飞书网络。
- 新增 `services/customer_crm_sync.py`：
  - 客户一行、跟进事实一行；
  - 两类 `FeishuBitableRecord` 映射；
  - 精确键收养、结果不确定时 reconciliation、逐条失败隔离、重跑幂等；
  - Base 仅可回写 `CRM阶段`、`下次跟进时间`、`跟进备注`、`联系结果`、`客户标签`；
  - 校验同步版本和远端更新时间，人工阶段变化落时间线与跟进事实。
- 新增客户列表、详情、时间线和同步 Operator API；写接口强制非空幂等键。
- 生成 Base 客户 record 深链和稳定妙搭客户详情深链数据，不实现或发布妙搭客户中心。

## TDD 证据

实现过程按行为分层先观察失败，再写最小实现：

- 模型字段、迁移结构、`promote` 跟进事实先失败，再完成模型/迁移实现。
- CRM 投影、幂等、单条失败隔离、reconciliation、白名单冲突与重复 pull 先失败，再完成同步服务。
- Operator 客户列表、详情、时间线、网关边界和同步幂等键先失败，再完成 API。
- 真实 Base 暴露的字段名/枚举差异先由测试锁定，再对齐现有 `客户`、`课程/考试`、`下一步` 和高/中/低选项。
- 空日期投影测试先得到 `'' is not None` 失败，再改为 Base 日期字段使用 `null`。
- 真实 API 暴露迁移客户版本为 0 时错误 404；新增测试先失败，再取消把同步版本误当客户身份的条件。
- lark-cli record list 不含远端更新时间；新增 record history 测试先得到 `AttributeError`，再通过单记录历史读取补齐冲突元数据。
- deferred candidate 曾可被显式同步或显示为客户；两个测试先失败，再把 `status=qualified` 作为正式客户边界。
- 空 record ID 的创建结果曾会误标成功；测试先失败，再进入 `reconciliation_unknown` 并禁止重建。
- CRM 阶段合同测试先失败，再完整对齐统一规格 6.2；迁移测试同时锁定 `new_customer` 回填和确定性初始客户事实。
- 正式客户进入 `invalid/无效` 后曾被错误隐藏；列表与同步测试先失败，再统一以 `Lead.status=qualified` 判断客户身份。

## 自动化验证

简报指定测试：

```text
/Users/xiaohao30000/aixhs666/.venv/bin/pytest tests/test_customer_crm_models.py tests/test_customer_crm_sync.py tests/test_feishu_customer_followup.py tests/test_customer_progression.py tests/test_operator_api.py tests/test_operator_gateway.py -q
61 passed, 1 warning in 1.12s
```

全量回归：

```text
/Users/xiaohao30000/aixhs666/.venv/bin/pytest -q
557 passed, 7 skipped, 1 warning in 26.42s
```

`git diff --check`：通过。

唯一 warning 为既有 FastAPI TestClient 对 httpx2 的弃用提示，本任务未新增依赖。

## 真实 PostgreSQL 验收

使用主运行目录真实环境变量和既有 Python 3.12 虚拟环境执行：

```text
迁移前：0017_customer_timeline_events
upgrade：0017_customer_timeline_events -> 0018_customer_crm
迁移后：0018_customer_crm (head)
```

- 迁移在 PostgreSQL 事务 DDL 下成功完成。
- 12 个既有 `qualified` Lead 均回填为统一规格阶段 `new_customer`，初始同步版本为 0。
- 迁移为每个既有正式客户幂等补一条确定性初始客户事实，事件键为 `crm-migration-customer:{customer_id}`；真实库共补 12 条。
- 真实库在审查发现状态合同问题前已登记 revision `0018`；修正最终迁移文件后，使用与最终迁移等价的幂等 ORM 操作纠正这 12 个阶段并补齐事实。新环境直接执行最终 `0018` 会得到相同结果。
- 真实客户 `customer_id=147` 用于闭环验收；未改变其资格状态，未生成发送任务。
- 最终 PostgreSQL：`customer_id=147`、`crm_stage=new_customer`、`crm_sync_version=2`、`operator_note=null`；初始事实 ID 为 4。

## 真实 Base 非破坏迁移

目标 Base：`RVtDb7nGkabAMbsDkA0cvxdOnld`。所有读写均使用已验证的用户身份和 `lark-cli base +... --as user`；没有浏览器手工搭表。

### 写前快照

| 对象 | 写前状态 |
|---|---:|
| 表数量 | 4 |
| `客户跟进表` | 10 行、11 字段、1 视图 |
| `AI筛选客户线索` | 122 行 |
| `AI筛选证据明细` | 123 行 |
| `系统控制台` | 1 行 |

真实客户表已有其他集成使用其表名，因此保留 `客户跟进表`，没有冒险重命名；新增 `客户 CRM` 视图明确其 CRM 用途。

### Schema 增量

在现有客户表仅新增 21 个字段：

```text
后端客户 ID、平台用户 ID、主页链接、地区、需求摘要、CRM阶段、
下次跟进时间、最近联系时间、联系结果、跟进备注、客户标签、
来源 Campaign、关联线索、关联证据、AI判断、运行批次、
发送状态/证据、妙搭详情链接、同步版本、同步状态、最近同步时间
```

新增表 `跟进记录`（table ID `tblkxsjlp22uv9DX`），共 15 个字段：

```text
跟进记录 ID、后端客户 ID、关联客户、发生时间、操作类型、联系渠道、
联系目标、内容、客户回复、本次结果、下一步、下次跟进时间、来源入口、
平台发送证据、是否完成
```

新增视图及过滤：

| 表 | 视图 | 过滤 |
|---|---|---|
| 客户跟进表 | 客户 CRM | 无 |
| 客户跟进表 | 待首次联系 | `CRM阶段` 包含 `待首次联系` |
| 客户跟进表 | 今天需要联系 | `下次跟进时间 == Today` |
| 跟进记录 | 全部跟进记录 | 无 |
| 跟进记录 | 待处理跟进 | `是否完成 == false` |

审查阶段发现最初创建的 `CRM阶段` 选项沿用了旧状态名。完成写前读取和 dry-run 后，仅向本任务新增的字段追加统一规格选项 `新客户`、`话术已确认`、`等待发送`、`已联系待回复`、`客户已回复`、`沟通中`、`有明确意向`、`已转化`、`暂缓`、`暂时失联`、`无效`；旧选项全部保留，没有删除或转换已有选项。

### 写后证明

| 对象 | 写后状态 | 说明 |
|---|---:|---|
| 客户跟进表 | 11 行、32 字段、4 视图 | 增加 1 个真实客户投影 |
| AI筛选客户线索 | 122 行 | 未变化 |
| AI筛选证据明细 | 123 行 | 未变化 |
| 系统控制台 | 1 行 | 未变化 |
| 跟进记录 | 1 行、15 字段、3 视图 | 增加客户 147 的真实初始客户事实投影 |

没有删除任何字段、表、视图或记录；写前已有的 10 条客户记录及候选、证据、控制记录均未修改，没有覆盖未知数据。唯一 field update 是对本任务新建的 `CRM阶段` 字段追加选项。

## 真实客户幂等 upsert

选择既有真实 `qualified` 客户 `147`：

1. 写前按 `后端客户 ID=147` 精确查询为 0 行。
2. 第一次 CRM sync 返回 `customers_synced=1`、无失败、无冲突。
3. 第二次 CRM sync 同样成功并复用 PostgreSQL 映射。
4. Base 精确查询始终只有 1 行，record ID 为 `recvpxkvVZRcv6`。
5. PostgreSQL `FeishuBitableRecord` 指向相同 Base/table/record，状态为 `synced`。
6. 最终客户表总数由 10 增至 11，没有重复客户。

## 真实跟进事实幂等 upsert

迁移为客户 147 创建初始事实 `followup_id=4`、事件键 `crm-migration-customer:147`、操作类型 `新客户`、结果 `completed`、来源 `0018_customer_crm`：

1. 第一次真实 sync 返回 `followups_synced=1`。
2. 第二次真实 sync 再次返回 `followups_synced=1`，复用同一 PostgreSQL 映射。
3. Base 按 `跟进记录 ID=4` 精确查询始终只有 1 行，record ID 为 `recvpxpCIVE6CC`。
4. PostgreSQL `customer_followup_record` 映射指向同一 Base/table/record，状态为 `synced`。
5. Base 最终跟进表总数为 1，没有重复跟进记录。

## 白名单可逆回写与恢复

选择白名单字段 `跟进备注`：

| 阶段 | Base | PostgreSQL | Operator API |
|---|---|---|---|
| 原值 | `null`，版本 0 | `null`，版本 0 | `null`，版本 0 |
| 临时验收值 | `V19-02可逆验收-20260716`，版本 0 | pull 后同值，版本 1 | HTTP 200，同值，版本 1 |
| 恢复后 | `null`，版本 2 | `null`，版本 2 | HTTP 200，`null`，版本 2 |

- pull 返回 `customers_synced=1`、`conflicted=0`、`failed=0`。
- lark-cli 通过单记录 history 的最新 `create_time` 提供远端更新时间；版本和时间比较均通过后才允许回写。
- 恢复时后端将备注改回原值并把版本单调递增到 2，再由正常 push 恢复 Base；没有倒退版本。
- 最终三端一致：客户 ID 147、阶段 `new_customer/新客户`、同步版本 2、备注 `null`、同步状态 `synced`，Base record ID `recvpxkvVZRcv6`。

## Operator API 与边界

已验证：

- `GET /operator/api/customers`
- `GET /operator/api/customers/147`
- `GET /operator/api/customers/147/timeline`
- `POST /operator/api/customers/sync`（非空幂等键校验）
- 客户详情返回稳定 `customer_id`、Base record 深链、妙搭客户深链、同步状态、下一步和版本。
- 迁移后的版本 0 正式客户可见；非正式候选不进入客户 API；正式客户进入 `invalid/无效` 阶段后仍可见、可同步。
- Operator Gateway 保留 `/health` 与受 token 保护的最小 Operator router；`/api/leads`、`/ops` 和飞书 callback 不开放。

真实一致性通过本地 Operator Gateway 应用的受认证 TestClient 读取真实 PostgreSQL 验证；本任务没有发布或重启公网服务。

## 非触发证明

- 没有调用任何小红书采集命令。
- 没有创建或执行公开回复发送任务。
- 没有调用私信、回复检查或定时调度。
- 没有发布妙搭、推送分支、创建 PR 或合并代码。

## 已知风险

- 客户表为兼容既有集成保留名称 `客户跟进表`；`客户 CRM` 目前是明确用途的视图。是否在后续统一物理表名应由主控另行决策。
- lark-cli 的 record list 不含远端更新时间；当前只对具有后端客户 ID 的待处理记录逐条读取 history。正确性已验证，但大量人工编辑时会增加 Base API 延迟。
- 同步 API 强制要求幂等键，实体写入由精确键和持久映射保证幂等；请求级幂等键目前不单独落账。
- 既有 `services/feishu_customer_followup.py` 为兼容保留；V19-02 的 CRM 双向同步应以 `services/customer_crm_sync.py` 为准。
- 未设置妙搭公网客户中心 URL 时，妙搭深链为稳定相对路径；完整客户中心和发布属于 V19-04。
- 为兼容此前写入的 Base 值，`CRM阶段` 暂时保留旧选项；后端只生成和接受统一规格的正式阶段值。

## 提交

```text
5613f2c feat: add customer CRM facts
095e92c feat: sync customer CRM with Feishu Base
c92a849 feat: expose customer CRM operator APIs
0de5ede fix: align CRM sync with live Base schema
5379749 fix: support migrated CRM customers in live sync
b19403e docs: verify V19-02 Base CRM
d1ddd28 fix: keep candidates out of customer CRM
1908a94 fix: align CRM stages and backfill customer facts
21f5959 fix: retain invalid customers in CRM
```
