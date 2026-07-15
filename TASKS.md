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
| AI 自动获客最小闭环 | DONE_CODE：`leads`、`lead_evidence`、`enrichment_tasks`、历史回填、Pipeline 增量接入和 `/leads` 客户判断工作台已完成 |
| 规则辅助 + LLM 主筛选 | DONE：`lead_screening_results` 结构化保存 LLM 判断，`leads-llm-screen` 可手动执行数据库 → LLM → 数据库 |
| 统一 LLM/飞书流程编排 | DONE_CODE：复用 `lead_screening_results` 增加 `workflow_status`、`attempt_count`、`last_error`，`lead-flow-once` 可按状态推进下一步；LLM 使用 `screening` 领取态，飞书发送使用 `sending` 领取态，`send_uncertain` 暴露不能自动重发的不确定结果 |
| 飞书 LLM 审核闭环 | DONE_REAL：真实点击“有效/无效/暂时观察”已更新数据库并把原卡片改成“已处理”；当前 live 验收未启用签名密钥，签名路径由测试覆盖 |
| 飞书话术审批闭环 | DONE_CODE：点击“有效”后可生成话术审批卡；飞书内点击“发送”现在只审批入库为 `approved_to_send`，真实小红书发送拆到独立入口，避免回调卡住 |
| Task 7 飞书审批评论回复 | DONE_AUTOMATED / LIVE_BLOCKED：实现、运维文档和安全合同测试完成；真实小红书发送仍待准备专用目标、selector probe 和飞书人工明确批准，禁止声称已发送成功 |
| 飞书 AI 筛选工作台 | DONE：`AI筛选客户线索` 71 条、`AI筛选证据明细` 72 条已写入 Base，证据已双向关联，卡片视图已创建 |
| 飞书 AI 筛选增量同步 | DONE_CODE：`feishu-ai-review-sync` 可把 `lead_screening_results` 的 DeepSeek 新结果增量写入 AI 筛选客户线索/证据明细表，重复执行不重复创建；字段顺序已按运营视角业务字段前置 |
| 飞书系统控制台 | DONE：`系统控制台` 表已创建，`run-control-panel-once` 只在人为设置 `开始执行=是，开始` 后执行一次并写回结果 |
| `/ops` 管理员边界 | DONE_CODE：普通运营入口改为 `/leads`/飞书表，`/ops` 明确为管理员控制台，采集、恢复、重试、创建任务等危险操作增加提示和确认 |
| Pipeline 自动闭环测试 | DONE：Mock 完整闭环、幂等、失败恢复、API/CLI 已覆盖 |
| 自动测试通过 | DONE：2026-07-14 `pytest -q` 为 494 passed, 7 skipped, 1 warning |
| SQLite 验证通过 | DONE：默认测试覆盖 |
| PostgreSQL 验证通过 | DONE：migration、runtime check、`pytest -m postgres -q` 已在本机 PostgreSQL 执行 |
| 真实小红书验证通过 | DONE：MediaCrawler 持久登录态已创建，live PostgreSQL 已入库 114 内容、309 评论、403 用户 |
| 真实 Pipeline Runner 验证通过 | PARTIAL：历史真实库和飞书写入已验证；长期稳定运行和新一轮小规模采集仍需观察 |
| 真实潜在客户回填验证通过 | DONE：本机历史库经人工校正后保留 3 个真实家长为可跟进，广告/无需求自动候选已清空，待完善 0，可跟进 3 |
| 真实飞书验证通过 | DONE：lark-cli 用户身份已验证 Base 建表、建字段、写记录、更新记录、创建视图和读记录 |
| 完整闭环通过 | PARTIAL：飞书人工审核和话术审批入库已通过；真实小红书私信发送因当前浏览器/网络环境暂时搁置；长期无人值守运行和新数据自动进入 AI 筛选表未完成 |

当前本机自动测试结果：

```text
.venv/bin/pytest -q
494 passed, 7 skipped, 1 warning

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

2026-07-14 评论回复子项进展：代码已改为远程 Windows CDP + 持久发送任务，回调快速返回，真实控件顺序已修复；Worker 强制要求 `remote_cdp` 和非空 CDP URL，禁止配置遗漏时回退到 Mac 本地浏览器。定向测试 `84 passed, 3 skipped, 1 warning`，全量测试 `494 passed, 7 skipped, 1 warning`。live selector probe 与单条发送仍阻塞于远程发射器 CDP/SSH 当前主动断开，以及测试目标和飞书/Base live 配置未提供。

阻塞：

- 本机没有 Docker：`docker compose up` 返回 `command not found`。
- 本机没有运行 PostgreSQL：`alembic upgrade head` 连接 `localhost:5432` 被拒绝。
- 未配置 `POSTGRES_TEST_DATABASE_URL`，PostgreSQL 并发测试跳过。
- 未配置小红书 live 登录 profile。
- 未配置飞书真实凭证。

## V16 飞书任务中心与 Skill Runtime

- [x] V16-01 `screen_historical_leads` 完整纵向任务产品闭环：模型、Registry、Runtime、Worker、飞书卡片/回调、可选 Base 投影、测试与文档。
- [x] V16-02 修复真实 Card 2.0 回调：解析 `event.action.value.action`，返回官方 `toast + raw card`，修正签名算法并支持加密回调；当时公网协议探针 HTTP 200，真实用户点击由 V16-03 完成。
- [x] V16-03 完成真实“创建任务”回调验收并新增 `docs/FEISHU_CARD_CALLBACK_RUNBOOK.md`：发布应用 `1.0.2`、重启同域名 localtunnel、发送新卡后真实点击创建 Skill Run `#8`，API 返回 HTTP 200。
- [x] V16-04 完成 Run `#8` 全流程真实验收：修复 Card 2.0 select/form submit、启动 Worker task `#358` 处理 50/50、修复 Worker `.env` 加载和 bot 身份消息 PATCH，最终同卡显示任务完成。

### V16-LIVE-RESULT — 结果详情与 Base 真实同步补验收（DONE，2026-07-15）

- 修复 `skill_result_<id>` 重复渲染完成摘要的问题，交付独立结果详情卡。
- dry-run 明确提示未写入，不再显示成误导性的成功摘要。
- Run `#8` 复用现有 50 个筛选结果，真实同步客户 50、证据 50，失败 0。
- 恢复 PostgreSQL 远端映射并更新同一张飞书任务卡；未访问小红书、未发送评论或私信。

## V17 人工审核工作台与 Founder Copilot

- [x] V17-00 固化产品设计和专用 Codex Handoff：`docs/FOUNDER_COPILOT.md`、`docs/FOUNDER_COPILOT_HANDOFF.md`。
- [ ] V17-01 补齐客户线索主表审核字段并优化卡片视图。
- [ ] V17-02 新增审核记录表，保留每次人工判断历史。
- [ ] V17-03 创建有效、无效、待二审和重新分析工作流。
- [ ] V17-04 将审核结果幂等同步回 PostgreSQL。
- [ ] V17-05 增加 AI/人工一致率、误判原因和 Campaign 效果统计。

Founder Copilot 默认约每 2–3 天基于真实任务证据反馈一次，由 Codex 判断具体时机；证据不足或正在处理线上事故时应延后，不得机械生成评价。

## V18 妙搭运营控制台

- [x] V18-01 交付并发布“今日工作台”MVP：妙搭操作台、NestJS BFF、FastAPI 聚合接口、线索/任务/Worker 状态和异常降级。线上应用已发布；稳定公网 FastAPI 与线上环境变量归入 V18-05。
- [ ] V18-02 在线索审核页实现有效、无效、待二审、重新分析和进入跟进动作。
- [ ] V18-03 在任务中心实现 Skill 模板、参数预览、执行进度和结果详情。
- [ ] V18-04 在 Campaign 中心实现行业模板、客户配置、版本发布和样本测试。
- [ ] V18-05 完成稳定后端托管、飞书入口、角色权限和运营审计。

V18 使用妙搭承载可视化与操作体验，现有 FastAPI/PostgreSQL/Worker 继续承载核心业务与事实数据。本轮只执行 V18-01，不提前实现后续写操作。
