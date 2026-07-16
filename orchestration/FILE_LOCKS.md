# 文件锁登记表

> 由主控会话维护。派发子任务前必须检查。

| 任务 | Worker | 锁定路径 | 模式 | 开始时间 | 释放条件 |
|---|---|---|---|---|---|
| V19-04 | W1 | `miaoda-console/client/src/app.tsx`; `miaoda-console/client/src/api/operator.ts`; `miaoda-console/client/src/types/operator.ts`; `miaoda-console/client/src/features/operator/operator-view-model.ts`; `miaoda-console/client/src/pages/**`; `miaoda-console/client/src/components/operator/**`; `miaoda-console/server/modules/operator/operator.controller.ts`; `miaoda-console/server/modules/operator/operator.service.ts`; `miaoda-console/test/unit/**`; `miaoda-console/README.md`; V19-04 双报告 | INTERFACE / WRITE | 2026-07-16 | 主控验收、合并并完成妙搭发布后释放 |

模式：

- WRITE：其他任务不得修改
- MIGRATION：禁止其他数据库迁移并行
- INTERFACE：禁止其他任务修改同一公共接口
- READ_SHARED：允许其他任务只读
