# V19-01 统一客户推进验收报告

日期：2026-07-16

## 交付范围

- 新增 `customer_timeline_events`，以唯一 `event_key` 保存客户推进审计事件。
- 新增统一客户推进服务，支持 `promote`、`defer`、`reject`。
- 妙搭 Operator API 返回客户阶段、下一步和时间线事件，不再只返回被修改的 Lead。
- 飞书“有效”审核与妙搭“推进为客户”调用同一推进服务。
- 妙搭审核动作收敛为“推进为客户、暂缓判断、淘汰线索”。
- 妙搭明确显示客户编号、当前阶段和下一步。

## 自动化验证

- 后端全量：`537 passed, 7 skipped, 1 warning in 32.58s`。
- 妙搭 Jest：`9 passed`。
- 妙搭 server/client TypeScript 检查通过。
- ESLint、Stylelint 通过。
- 妙搭生产构建通过。
- Alembic head：`0017_customer_timeline_events`。
- `git diff --check` 通过。

## 真实 PostgreSQL 验收

1. 真实 PostgreSQL 从 `0016_skill_runs` 升级到 `0017_customer_timeline_events`。
2. 数据库当时 Lead 状态分布：`ignored=6`、`needs_review=57`、`qualified=12`。
3. 选择真实 Lead `#147`、最新 Screening `#1`。
4. 对全部受影响 Lead/Screening 字段建立快照。
5. 调用真实 `progress_operator_lead(action="promote")`。
6. 真实创建时间线事件 `#1`，并确认 Lead 进入 `followup_status=pending`。
7. 按快照恢复 Lead 和 Screening，并删除仅用于验收的时间线事件。
8. 恢复后逐字段一致，输出 `restored=true`，没有遗留测试业务状态。

## 真人交互变化

- 删除容易混淆的“确认有效”和“进入跟进”双按钮。
- 提供三个业务动作：推进为客户、暂缓判断、淘汰线索。
- 暂缓操作要求原因和重新提醒时间。
- 提交期间动作按钮禁用，防止重复点击。
- 每次点击携带幂等键。
- 完成反馈示例：`已处理客户 #151｜当前阶段：待首次联系｜下一步：准备公开回复`。

## 明确未包含

- Base CRM 表结构和双向同步属于 V19-02。
- Run 人类结果报告与每日 50 条属于 V19-03。
- 公开回复草稿确认和真实发送属于 V19-05。
- 14:00、15:00、21:00 调度与回复检查属于 V19-06。
- 本次尚未发布新的妙搭 Release；源码合入 `main` 后需要走妙搭导出和发布流程才能在线可见。

