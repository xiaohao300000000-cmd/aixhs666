# 文件锁登记表

> 由主控会话维护。派发子任务前必须检查。

| 任务 | Worker | 锁定路径 | 模式 | 开始时间 | 释放条件 |
|---|---|---|---|---|---|
| V19-04-H1 | W1 | `miaoda-console/client/src/features/operator/operator-view-model.ts`; `miaoda-console/client/src/pages/LeadReviewPage.tsx`; `miaoda-console/test/unit/operator-view-model.spec.ts`; `docs/reports/V19_04_MIAODA_EXPERIENCE_VERIFICATION.md`; `orchestration/reports/V19-04-H1.md` | WRITE | 2026-07-17 | 主控验收、合并、重新发布并完成线上空/完成态复验后释放 |

模式：

- WRITE：其他任务不得修改
- MIGRATION：禁止其他数据库迁移并行
- INTERFACE：禁止其他任务修改同一公共接口
- READ_SHARED：允许其他任务只读
