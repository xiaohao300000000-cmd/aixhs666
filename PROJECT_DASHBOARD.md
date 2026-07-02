# 项目可视化进度表

> 本文件只能由主控会话更新。子会话不得修改。

## 总体进度

```text
已完成：22 / 22
总体进度：100%

[████████████████████] 100%
```

## 当前状态

| 项目 | 当前值 |
|---|---|
| 当前阶段 | V0 真实数据闭环修正 |
| 当前主任务 | V01-V05 代码完成；V06 真实闭环验收阻塞 |
| 执行会话 | 主控单会话 |
| 当前分支 | `feat/v0-real-data-loop` |
| 阻塞数量 | 5 |
| 最后更新 | 2026-07-02：真实 adapter、worker、DB 幂等、飞书传输、数据库看板已实现；真实闭环因环境/凭证未完成 |

## 阶段进度

| 阶段 | 范围 | 任务 | 已完成 | 进度 | 状态 |
|---|---|---:|---:|---:|---|
| 阶段 0 | 项目地基 | T01–T06 | 6/6 | 100% | 已完成 |
| 阶段 1 | 小红书采集 MVP | T07–T10 | 4/4 | 100% | 已完成 |
| 阶段 2 | 动态采集与来源评分 | T11–T13 | 3/3 | 100% | 已完成 |
| 阶段 3 | AI 新词发现 | T14–T16 | 3/3 | 100% | 已完成 |
| 阶段 4 | 事件雷达与预警 | T17–T19 | 3/3 | 100% | 已完成 |
| 阶段 5 | 看板与内容洞察 | T20–T21 | 2/2 | 100% | 已完成 |
| 阶段 6 | 第二平台评估 | T22 | 1/1 | 100% | 已完成 |

## 任务看板

| ID | 任务 | 阶段 | 依赖 | 状态 | 执行会话 | 分支 | 验收 |
|---|---|---|---|---|---|---|---|
| T01 | 仓库骨架 | 0 | 无 | DONE | W1 | `task/T01-repository-scaffold` | ACCEPT：CI 通过 |
| T02 | 核心数据模型 | 0 | T01 | DONE | W1 | `task/T02-core-data-models` | ACCEPT：CI 通过 |
| T03 | 任务状态机 | 0 | T02 | DONE | W1 | `task/T03-task-state-machine` | ACCEPT：CI 通过 |
| T04 | PlatformAdapter 与 Mock | 0 | T01 | DONE | W1 | `task/T04-platform-adapter-mock` | ACCEPT：CI 通过 |
| T05 | 去重与发现关系 | 0 | T02,T04 | DONE | W1 | `task/T05-dedup-discovery-relations` | ACCEPT：CI 通过 |
| T06 | 查询管理 API | 0 | T02,T03 | DONE | W1 | `task/T06-query-management-api` | ACCEPT：CI 通过 |
| T07 | 小红书搜索采集 | 1 | T04,T05,T06 | DONE | W1 | `task/T07-xhs-search-collection` | ACCEPT：`84b47e4`，40 passed |
| T08 | 小红书详情采集 | 1 | T07 | DONE | W1 | `task/T08-xhs-detail-collection` | ACCEPT：`e1d33fb`，45 passed |
| T09 | 小红书评论采集 | 1 | T08 | DONE | W1 | `task/T09-xhs-comment-collection` | ACCEPT：`a76cb0d`，52 passed |
| T10 | 断点续传与部分成功 | 1 | T03,T07,T09 | DONE | W1 | `task/T10-resume-partial-success` | ACCEPT：`3940496`，56 passed |
| T11 | 高价值内容池 | 2 | T09,T10 | DONE | W1 | `task/T11-high-value-source-pool` | ACCEPT：`e4d0631`，61 passed |
| T12 | 评论区动态预算 | 2 | T09,T11 | DONE | W1 | `task/T12-comment-dynamic-budget` | ACCEPT：`6f36f95`，74 passed |
| T13 | 查询与来源评分 | 2 | T06,T11 | DONE | W2 | `task/T13-query-source-scoring` | ACCEPT：`8699b21`，73 passed |
| T14 | 文本处理与低信息标记 | 3 | T05 | DONE | W2 | `task/T14-text-processing-low-info` | ACCEPT：`8b25692`，62 passed |
| T15 | 语义聚类与新词发现 | 3 | T14 | DONE | W3 | `task/T15-semantic-clustering-phrase-discovery` | ACCEPT：`243181d`，71 passed |
| T16 | 飞书新词审核 | 3 | T15 | DONE | W3 | `task/T16-feishu-phrase-review` | ACCEPT：`cbc43bc`，77 passed |
| T17 | 事件日历 | 4 | T06,T13 | DONE | W1 | `task/T17-event-calendar` | ACCEPT：`514e8b9`，97 passed |
| T18 | 需求事件链 | 4 | T02,T14 | DONE | W2 | `task/T18-demand-event-chain` | ACCEPT：`4d9ef37`，95 passed |
| T19 | 信号新鲜度与飞书预警 | 4 | T13,T17,T18 | DONE | W1 | `task/T19-signal-freshness-alerts` | ACCEPT：`e2809b7`，106 passed |
| T20 | 数据看板 | 5 | T13,T16,T19 | DONE | W1 | `task/T20-data-dashboard` | ACCEPT：`fbb8e44`，110 passed |
| T21 | 内容洞察输出 | 5 | T15,T20 | DONE | W1 | `task/T21-content-insights` | ACCEPT：`46a1b13`，114 passed |
| T22 | 第二平台评估 | 6 | T20,T21 | DONE | W1 | `task/T22-second-platform-evaluation` | ACCEPT：`9bf7f40`，120 passed |

## GitHub 可视化甘特图

```mermaid
gantt
    title AI 教育需求发现系统开发计划
    dateFormat  YYYY-MM-DD
    axisFormat  %m-%d

    section 阶段0 项目地基
    T01 仓库骨架               :t01, 2026-07-01, 1d
    T02 核心数据模型           :t02, after t01, 2d
    T03 任务状态机             :t03, after t02, 2d
    T04 PlatformAdapter 与 Mock:t04, after t01, 1d
    T05 去重与发现关系         :t05, after t02, 2d
    T06 查询管理 API           :t06, after t03, 1d

    section 阶段1 小红书 MVP
    T07 搜索采集               :t07, after t06, 3d
    T08 详情采集               :t08, after t07, 2d
    T09 评论采集               :t09, after t08, 3d
    T10 断点续传               :t10, after t09, 2d

    section 阶段2 动态采集
    T11 高价值内容池           :t11, after t10, 2d
    T12 评论动态预算           :t12, after t11, 2d
    T13 查询与来源评分         :t13, after t11, 2d

    section 阶段3 AI 新词发现
    T14 文本处理               :t14, after t05, 2d
    T15 聚类与新词发现         :t15, after t14, 3d
    T16 飞书新词审核           :t16, after t15, 2d

    section 阶段4 事件雷达
    T17 事件日历               :t17, after t13, 2d
    T18 需求事件链             :t18, after t14, 2d
    T19 新鲜度与预警           :t19, after t17, 2d

    section 阶段5 产品输出
    T20 数据看板               :t20, after t19, 3d
    T21 内容洞察               :t21, after t20, 2d

    section 阶段6 扩展
    T22 第二平台评估           :t22, after t21, 2d
```

> 日期只是初始排期模板。主控会话应根据实际进展调整，不得把估算当成宗教经典。

## 阻塞项

| ID | 阻塞内容 | 影响任务 | 负责人 | 处理状态 |
|---|---|---|---|---|
| V06-B1 | 本机没有 Docker，`docker compose up` 无法执行 | Docker/API/Worker/PostgreSQL 联调 | 用户/环境 | 待安装或提供远程环境 |
| V06-B2 | 本机 PostgreSQL `localhost:5432` 未运行 | `alembic upgrade head`、真实数据库闭环 | 用户/环境 | 待启动 |
| V06-B3 | `POSTGRES_TEST_DATABASE_URL` 未配置 | PostgreSQL 并发领取测试 | 用户/环境 | 待配置 |
| V06-B4 | 未配置小红书 live 登录 profile | 真实搜索/详情/评论/主页采集 | 用户/环境 | 待手动登录 |
| V06-B5 | 未配置飞书凭证 | 真实飞书发送与回调验证 | 用户/环境 | 待配置 |

## 最近完成

| 日期 | 任务 | 结果 | 报告 |
|---|---|---|---|
| 2026-07-01 | T01 仓库骨架 | ACCEPT，GitHub CI 通过 | `orchestration/reports/T01.md` |
| 2026-07-01 | T02 核心数据模型 | ACCEPT，GitHub CI 通过 | `orchestration/reports/T02.md` |
| 2026-07-01 | T03 任务状态机 | ACCEPT，GitHub CI 通过 | `orchestration/reports/T03.md` |
| 2026-07-01 | T04 PlatformAdapter 与 Mock | ACCEPT，GitHub CI 通过 | `orchestration/reports/T04.md` |
| 2026-07-01 | T05 去重与发现关系 | ACCEPT，GitHub CI 通过 | `orchestration/reports/T05.md` |
| 2026-07-01 | T06 查询管理 API | ACCEPT，GitHub CI 通过 | `orchestration/reports/T06.md` |
| 2026-07-02 | T07 小红书搜索采集 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T07.md` |
| 2026-07-02 | T08 小红书详情采集 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T08.md` |
| 2026-07-02 | T09 小红书评论采集 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T09.md` |
| 2026-07-02 | T10 断点续传与部分成功 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T10.md` |
| 2026-07-02 | T11 高价值内容池 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T11.md` |
| 2026-07-02 | T12 评论区动态预算 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T12.md` |
| 2026-07-02 | T13 查询与来源评分 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T13.md` |
| 2026-07-02 | T14 文本处理与低信息标记 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T14.md` |
| 2026-07-02 | T15 语义聚类与新词发现 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T15.md` |
| 2026-07-02 | T16 飞书新词审核 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T16.md` |
| 2026-07-02 | T17 事件日历 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T17.md` |
| 2026-07-02 | T18 需求事件链 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T18.md` |
| 2026-07-02 | T19 信号新鲜度与飞书预警 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T19.md` |
| 2026-07-02 | T20 数据看板 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T20.md` |
| 2026-07-02 | T21 内容洞察输出 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T21.md` |
| 2026-07-02 | T22 第二平台评估 | ACCEPT，本地 pytest 通过 | `orchestration/reports/T22.md` |

## 下一步

1. 准备 Docker/PostgreSQL 环境并设置 `DATABASE_URL`、`POSTGRES_TEST_DATABASE_URL`
2. 配置小红书浏览器 profile 并手动登录
3. 配置飞书 Webhook 或应用凭证
4. 执行 V06 真实闭环验收，达标后再讨论第二平台


## 并发管理

| 指标 | 当前值 |
|---|---|
| 默认 Worker 数 | 2 |
| 当前启用 | W1、W2 待机 |
| 建议上限 | 3 |
| 硬上限 | 4 |
| 待验收上限 | 2 |
| 当前待验收 | 0 |
| 当前文件锁 | 0 |

详细状态见：

- `orchestration/WORKER_REGISTRY.md`
- `orchestration/FILE_LOCKS.md`
- `docs/CONCURRENCY_POLICY.md`
