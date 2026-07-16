# 文件锁登记表

> 由主控会话维护。派发子任务前必须检查。

| 任务 | Worker | 锁定路径 | 模式 | 开始时间 | 释放条件 |
|---|---|---|---|---|---|
| V19-02 | W1 | `storage/models.py`; `alembic/versions/0018_customer_crm.py`; `services/customer_crm_sync.py`; `services/feishu_customer_followup.py`; `services/customer_progression.py`; `services/operator_customers.py`; `integrations/feishu/bitable.py`; `apps/api/routes/operator_api.py`; `apps/operator_gateway.py`; 对应测试与 V19-02 报告 | MIGRATION / INTERFACE / WRITE | 2026-07-16 | 主控验收并合并 V19-02 后释放 |

模式：

- WRITE：其他任务不得修改
- MIGRATION：禁止其他数据库迁移并行
- INTERFACE：禁止其他任务修改同一公共接口
- READ_SHARED：允许其他任务只读
