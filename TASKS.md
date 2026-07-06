# 任务清单

状态：

- TODO
- IN_PROGRESS
- BLOCKED

- DONE

## V0 真实闭环验收状态

| 项目 | 状态 |
|---|---|
| 代码完成 | DONE：真实 adapter、Worker、PostgreSQL 幂等/并发、飞书 transport/callback、数据库看板、运行诊断、HTML 控制台 |
| Agent 中立 Pipeline Runner | DONE：`services/pipeline_runner.py`、`pipeline_runs`、CLI、REST 已接入主流程 |
| AI 自动获客最小闭环 | DONE_CODE：`leads`、`lead_evidence`、`enrichment_tasks`、历史回填、Pipeline 增量接入和 `/leads` 获客页面已完成 |
| 规则辅助 + LLM 主筛选 | DONE：`lead_screening_results` 结构化保存 LLM 判断，`leads-llm-screen` 可手动执行数据库 → LLM → 数据库 |
| 飞书 LLM 审核闭环 | PARTIAL_REAL：卡片发送、message_id 保存、FastAPI 验签幂等回调和卡片更新逻辑已完成；已真实发送 1 条审核卡；真实点击回调需公网回调 URL |
| 飞书 AI 筛选工作台 | DONE：`AI筛选客户线索` 71 条、`AI筛选证据明细` 72 条已写入 Base，证据已双向关联，卡片视图已创建 |
| 飞书系统控制台 | DONE：`系统控制台` 表已创建，`run-control-panel-once` 只在人为设置 `开始执行=是，开始` 后执行一次并写回结果 |
| Pipeline 自动闭环测试 | DONE：Mock 完整闭环、幂等、失败恢复、API/CLI 已覆盖 |
| 自动测试通过 | DONE：`pytest -q` 为 245 passed, 2 skipped |
| SQLite 验证通过 | DONE：默认测试覆盖 |
| PostgreSQL 验证通过 | DONE：migration、runtime check、`pytest -m postgres -q` 已在本机 PostgreSQL 执行 |
| 真实小红书验证通过 | DONE：MediaCrawler 持久登录态已创建，live PostgreSQL 已入库 114 内容、309 评论、403 用户 |
| 真实 Pipeline Runner 验证通过 | PARTIAL：历史真实库和飞书写入已验证；长期稳定运行和新一轮小规模采集仍需观察 |
| 真实潜在客户回填验证通过 | DONE：本机历史库经人工校正后保留 3 个真实家长为可跟进，广告/无需求自动候选已清空，待完善 0，可跟进 3 |
| 真实飞书验证通过 | DONE：lark-cli 用户身份已验证 Base 建表、建字段、写记录、更新记录、创建视图和读记录 |
| 完整闭环通过 | PARTIAL：飞书人工工作台已通过；长期无人值守运行和新数据自动进入 AI 筛选表未完成 |

V15 本机自动测试结果：

```text
.venv/bin/python -m pytest -q
245 passed, 2 skipped, 1 warning

.venv/bin/python -m pytest -m postgres -q
1 skipped, 170 deselected, 1 warning
```

飞书工作台当前真实数量：

```text
AI筛选客户线索：71
  高意向：10
  待人工确认：61
AI筛选证据明细：72
证据关联：72/72
系统控制台：已验证手动触发一次、执行后写回结果
```

## 全局执行规则

- 只有主控会话可以修改任务状态
- 子会话不得直接把任务改为 DONE
- 每个任务必须先创建 `orchestration/briefs/TXX.md`
- 每个任务完成后必须创建 `orchestration/reports/TXX.md`
- 依赖未完成的任务不得开始
- 项目总进度见 `PROJECT_DASHBOARD.md`

## T01 仓库骨架

状态：DONE

依赖：无

目标：

- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic
- pytest
- Docker Compose
- `.env.example`
- `/health`
- 基础 CI

验收：

- `docker compose up` 能启动
- `/health` 正常
- 测试通过
- 迁移可执行

## T02 核心数据模型

状态：DONE

依赖：T01

实现：

- queries
- contents
- comments
- public_profiles
- discovery_relations
- collection_tasks
- snapshots
- collection_events

验收：

- 唯一键和索引正确
- Alembic 迁移通过
- 数据模型测试通过

## T03 任务状态机

状态：DONE

依赖：T02

实现：

- 任务创建
- Worker 领取
- 超时恢复
- 重试
- partial
- cancel

验收：

- 状态转换有测试
- 失败不影响其他任务
- 超时任务可恢复

## T04 PlatformAdapter 与 Mock 采集器

状态：DONE

依赖：T01

实现：

- 统一数据对象
- PlatformAdapter
- Mock Adapter
- 测试数据

验收：

- Mock 数据可跑通查询、内容、评论和用户入库

## T05 去重与发现关系

状态：DONE

依赖：T02、T04

实现：

- 内容去重
- 评论去重
- 多查询发现关系
- 文本哈希

验收：

- 同一内容只存一份
- 多查询可产生多条发现关系

## T06 查询管理 API

状态：DONE

依赖：T02、T03

实现：

- 查询 CRUD
- 启停
- 优先级
- 手动运行
- 查询统计基础字段

## T07 小红书搜索采集

状态：DONE

依赖：T04、T05、T06

实现：

- 复用 Chrome 登录态
- 搜索结果
- 分页或游标
- L0 入库
- 原始快照

## T08 小红书详情采集

状态：DONE

依赖：T07

实现：

- 正文
- 作者
- 时间
- 标签
- 互动数据
- L1 入库

## T09 小红书评论采集

状态：DONE

依赖：T08

实现：

- 一级评论
- 二级回复
- 评论关系
- 游标
- L2 入库

## T10 断点续传与部分成功

状态：DONE

依赖：T03、T07、T09

实现：

- 搜索游标
- 评论游标
- Worker 重启恢复
- partial 状态
- 分段重试

## T11 高价值内容池

状态：DONE

依赖：T09、T10

实现：

- 帖子追踪
- 种子账号
- 竞品账号
- 增量检查
- 追踪频率

## T12 评论区动态预算

状态：DONE

依赖：T09、T11

实现：

- 批次指标
- 继续条件
- 停止条件
- 强制上限

## T13 查询与来源评分

状态：DONE

依赖：T06、T11

实现：

- 新增率
- 新用户率
- 新表达率
- 重复率
- 失败率
- 任务价值分

## T14 文本处理与低信息标记

状态：DONE

依赖：T05

实现：

- 清洗
- 低信息标签
- 字段提取
- 基础规则

## T15 语义聚类与新词发现

状态：DONE

依赖：T14

实现：

- Embedding
- 语义簇
- 新表达
- 代表样本
- 候选查询

## T16 飞书新词审核

状态：DONE

依赖：T15

实现：

- 候选词推送
- 批准
- 拒绝
- 转成查询
- 状态回写

## T17 事件日历

状态：DONE

依赖：T06、T13

实现：

- 教育事件
- 时间范围
- 关联查询
- 事件前后优先级调整

## T18 需求事件链

状态：DONE

依赖：T02、T14

实现：

- demand_events
- 同一公开账号时间序列
- 事件分类
- 证据原文

## T19 信号新鲜度与飞书预警

状态：DONE

依赖：T13、T17、T18

实现：

- freshness_class
- 预警排序
- 飞书卡片
- 人工反馈

## T20 数据看板

状态：DONE

依赖：T13、T16、T19

展示：

- 每日新增
- 重复率
- 查询产出
- 来源评分
- 新词数量
- 失败任务
- 数据完整度

## T21 内容洞察输出

状态：DONE

依赖：T15、T20

实现：

- 高频问题
- 新增焦虑点
- 内容选题
- 资料包主题
- 直播主题

## T22 第二平台评估

状态：DONE

依赖：T20、T21

输出：

- 抖音、知乎、B站、微博和搜索引擎对比
- 推荐第二平台
- 预估成本
- 接入计划

## V0 真实数据闭环修正任务

> 以下状态以代码和本机实际运行结果为准，不沿用 T01-T22 的“100% 完成”口径。

## V01 真实小红书采集器

状态：DONE_CODE / LIVE_PENDING

结果：

- 已新增 Playwright `collectors/xiaohongshu/` adapter。
- 已覆盖本地页面样本解析和接口映射测试。
- 未完成真实小红书登录后 live 采集验证。

## V02 Worker 运行入口

状态：DONE_CODE / PG_RUNTIME_PENDING

结果：

- 已新增 `python -m apps.worker`。
- 已支持 once、worker_id、轮询、恢复超时、partial/retry 和任务分发。
- 未完成真实 PostgreSQL 长运行 Worker 验证。

## V03 数据库并发与幂等

状态：DONE_CODE / PG_CONCURRENCY_PENDING

结果：

- 已实现 PostgreSQL `FOR UPDATE SKIP LOCKED` 领取逻辑。
- 已新增 `discovery_relations(query_id, content_id)` 唯一约束。
- 已实现 PostgreSQL discovery relation upsert。
- PostgreSQL 并发测试因缺少 `POSTGRES_TEST_DATABASE_URL` 跳过。

## V04 真实飞书集成

状态：DONE_CODE / LIVE_FEISHU_PENDING

结果：

- 已新增 webhook transport、dry-run、重试、密钥遮蔽、callback token/signature helper 和幂等回调记录。
- 已支持 `approve`、`reject`、`convert_to_query`。
- 未配置真实飞书凭证，未完成真实发送验证。

## V05 数据库看板统计

状态：DONE_CODE / LIVE_PG_DASHBOARD_PENDING

结果：

- 已新增数据库驱动的 `GET /dashboard/summary`。
- 已覆盖 SQLite 数据库聚合测试。
- 未完成 PostgreSQL/live 数据看板验证。

## V06 真实闭环验收

状态：BLOCKED

阻塞：

- 本机没有 Docker：`docker compose up` 返回 `command not found`。
- 本机没有运行 PostgreSQL：`alembic upgrade head` 连接 `localhost:5432` 被拒绝。
- 未配置 `POSTGRES_TEST_DATABASE_URL`，PostgreSQL 并发测试跳过。
- 未配置小红书 live 登录 profile。
- 未配置飞书真实凭证。
