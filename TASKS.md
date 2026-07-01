# 任务清单

状态：

- TODO
- IN_PROGRESS
- BLOCKED

- DONE

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

状态：TODO

依赖：T06、T13

实现：

- 教育事件
- 时间范围
- 关联查询
- 事件前后优先级调整

## T18 需求事件链

状态：TODO

依赖：T02、T14

实现：

- demand_events
- 同一公开账号时间序列
- 事件分类
- 证据原文

## T19 信号新鲜度与飞书预警

状态：TODO

依赖：T13、T17、T18

实现：

- freshness_class
- 预警排序
- 飞书卡片
- 人工反馈

## T20 数据看板

状态：TODO

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

状态：TODO

依赖：T15、T20

实现：

- 高频问题
- 新增焦虑点
- 内容选题
- 资料包主题
- 直播主题

## T22 第二平台评估

状态：TODO

依赖：T20、T21

输出：

- 抖音、知乎、B站、微博和搜索引擎对比
- 推荐第二平台
- 预估成本
- 接入计划
