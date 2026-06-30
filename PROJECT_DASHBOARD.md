# 项目可视化进度表

> 本文件只能由主控会话更新。子会话不得修改。

## 总体进度

```text
已完成：3 / 22
总体进度：14%

[███░░░░░░░░░░░░░░░░░] 14%
```

## 当前状态

| 项目 | 当前值 |
|---|---|
| 当前阶段 | 阶段 0：项目地基 |
| 当前主任务 | T04 PlatformAdapter 与 Mock |
| 执行会话 | W1 已分配 T04；W2 待机；W3/W4 关闭 |
| 当前分支 | 主控：`main` |
| 阻塞数量 | 0 |
| 最后更新 | 2026-07-01 05:27 CST：T04 独立执行对话已启动，等待报告 |

## 阶段进度

| 阶段 | 范围 | 任务 | 已完成 | 进度 | 状态 |
|---|---|---:|---:|---:|---|
| 阶段 0 | 项目地基 | T01–T06 | 3/6 | 50% | T04 进行中 |
| 阶段 1 | 小红书采集 MVP | T07–T10 | 0/4 | 0% | 未开始 |
| 阶段 2 | 动态采集与来源评分 | T11–T13 | 0/3 | 0% | 未开始 |
| 阶段 3 | AI 新词发现 | T14–T16 | 0/3 | 0% | 未开始 |
| 阶段 4 | 事件雷达与预警 | T17–T19 | 0/3 | 0% | 未开始 |
| 阶段 5 | 看板与内容洞察 | T20–T21 | 0/2 | 0% | 未开始 |
| 阶段 6 | 第二平台评估 | T22 | 0/1 | 0% | 未开始 |

## 任务看板

| ID | 任务 | 阶段 | 依赖 | 状态 | 执行会话 | 分支 | 验收 |
|---|---|---|---|---|---|---|---|
| T01 | 仓库骨架 | 0 | 无 | DONE | W1 | `task/T01-repository-scaffold` | ACCEPT：CI 通过 |
| T02 | 核心数据模型 | 0 | T01 | DONE | W1 | `task/T02-core-data-models` | ACCEPT：CI 通过 |
| T03 | 任务状态机 | 0 | T02 | DONE | W1 | `task/T03-task-state-machine` | ACCEPT：CI 通过 |
| T04 | PlatformAdapter 与 Mock | 0 | T01 | IN_PROGRESS | W1 | `task/T04-platform-adapter-mock` | 等待报告 |
| T05 | 去重与发现关系 | 0 | T02,T04 | TODO | 未分配 | - | 待验收 |
| T06 | 查询管理 API | 0 | T02,T03 | TODO | 未分配 | - | 待验收 |
| T07 | 小红书搜索采集 | 1 | T04,T05,T06 | TODO | 未分配 | - | 待验收 |
| T08 | 小红书详情采集 | 1 | T07 | TODO | 未分配 | - | 待验收 |
| T09 | 小红书评论采集 | 1 | T08 | TODO | 未分配 | - | 待验收 |
| T10 | 断点续传与部分成功 | 1 | T03,T07,T09 | TODO | 未分配 | - | 待验收 |
| T11 | 高价值内容池 | 2 | T09,T10 | TODO | 未分配 | - | 待验收 |
| T12 | 评论区动态预算 | 2 | T09,T11 | TODO | 未分配 | - | 待验收 |
| T13 | 查询与来源评分 | 2 | T06,T11 | TODO | 未分配 | - | 待验收 |
| T14 | 文本处理与低信息标记 | 3 | T05 | TODO | 未分配 | - | 待验收 |
| T15 | 语义聚类与新词发现 | 3 | T14 | TODO | 未分配 | - | 待验收 |
| T16 | 飞书新词审核 | 3 | T15 | TODO | 未分配 | - | 待验收 |
| T17 | 事件日历 | 4 | T06,T13 | TODO | 未分配 | - | 待验收 |
| T18 | 需求事件链 | 4 | T02,T14 | TODO | 未分配 | - | 待验收 |
| T19 | 信号新鲜度与飞书预警 | 4 | T13,T17,T18 | TODO | 未分配 | - | 待验收 |
| T20 | 数据看板 | 5 | T13,T16,T19 | TODO | 未分配 | - | 待验收 |
| T21 | 内容洞察输出 | 5 | T15,T20 | TODO | 未分配 | - | 待验收 |
| T22 | 第二平台评估 | 6 | T20,T21 | TODO | 未分配 | - | 待验收 |

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
| - | 当前无阻塞 | - | - | - |

## 最近完成

| 日期 | 任务 | 结果 | 报告 |
|---|---|---|---|
| 2026-07-01 | T01 仓库骨架 | ACCEPT，GitHub CI 通过 | `orchestration/reports/T01.md` |
| 2026-07-01 | T02 核心数据模型 | ACCEPT，GitHub CI 通过 | `orchestration/reports/T02.md` |
| 2026-07-01 | T03 任务状态机 | ACCEPT，GitHub CI 通过 | `orchestration/reports/T03.md` |

## 下一步

1. 启动独立执行对话 W1 执行 `orchestration/briefs/T04.md`
2. 等待 `orchestration/reports/T04.md`
3. 主控验收 T04 PlatformAdapter、Mock 数据和入库映射测试
4. T04 完成后继续派发 T05


## 并发管理

| 指标 | 当前值 |
|---|---|
| 默认 Worker 数 | 2 |
| 当前启用 | W1、W2 |
| 建议上限 | 3 |
| 硬上限 | 4 |
| 待验收上限 | 2 |
| 当前待验收 | 0 |
| 当前文件锁 | 2 |

详细状态见：

- `orchestration/WORKER_REGISTRY.md`
- `orchestration/FILE_LOCKS.md`
- `docs/CONCURRENCY_POLICY.md`
