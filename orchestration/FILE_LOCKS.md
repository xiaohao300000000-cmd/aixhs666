# 文件锁登记表

> 由主控会话维护。派发子任务前必须检查。

| 任务 | Worker | 锁定路径 | 模式 | 开始时间 | 释放条件 |
|---|---|---|---|---|---|
| V19-05 | W1 | `storage/models.py`; `alembic/versions/0021_contact_reply_two_step.py`; `services/contact_commands.py`; `services/customer_progression.py`; `services/operator_customers.py`; `services/customer_crm_sync.py`; `services/feishu_customer_followup.py`; `services/comment_reply_generation.py`; `integrations/feishu/comment_replies.py`; `apps/api/routes/operator_api.py`; `apps/api/routes/feishu_callbacks.py`; `apps/worker/comment_reply_prepare.py`; `apps/worker/comment_reply_send.py`; `apps/worker/main.py`; `apps/operator_gateway.py`; `miaoda-console/server/modules/operator/**`; `miaoda-console/client/src/api/operator.ts`; `miaoda-console/client/src/types/operator.ts`; `miaoda-console/client/src/features/operator/operator-view-model.ts`; `miaoda-console/client/src/pages/CustomerDetailPage.tsx`; 点名测试与双报告 | WRITE / MIGRATION / INTERFACE | 2026-07-17 | 主控完成范围审计、自动化、真实 PostgreSQL 非破坏证据和代码验收后释放；真实发送审批不作为代码锁释放前提 |

模式：

- WRITE：其他任务不得修改
- MIGRATION：禁止其他数据库迁移并行
- INTERFACE：禁止其他任务修改同一公共接口
- READ_SHARED：允许其他任务只读
