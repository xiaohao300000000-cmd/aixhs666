# 文件锁登记表

> 由主控会话维护。派发子任务前必须检查。

| 任务 | Worker | 锁定路径 | 模式 | 开始时间 | 释放条件 |
|---|---|---|---|---|---|
| T05 | W1 | `storage/**` | WRITE | 2026-07-01 05:38 CST | T05 验收并合并后释放 |
| T05 | W1 | `tests/test_dedup_discovery.py` | WRITE | 2026-07-01 05:38 CST | T05 验收并合并后释放 |

模式：

- WRITE：其他任务不得修改
- MIGRATION：禁止其他数据库迁移并行
- INTERFACE：禁止其他任务修改同一公共接口
- READ_SHARED：允许其他任务只读
