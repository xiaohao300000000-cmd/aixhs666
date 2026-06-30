# 文件锁登记表

> 由主控会话维护。派发子任务前必须检查。

| 任务 | Worker | 锁定路径 | 模式 | 开始时间 | 释放条件 |
|---|---|---|---|---|---|
| T04 | W1 | `collectors/**` | WRITE | 2026-07-01 05:25 CST | T04 验收并合并后释放 |
| T04 | W1 | `tests/test_platform_adapter_mock.py` | WRITE | 2026-07-01 05:25 CST | T04 验收并合并后释放 |

模式：

- WRITE：其他任务不得修改
- MIGRATION：禁止其他数据库迁移并行
- INTERFACE：禁止其他任务修改同一公共接口
- READ_SHARED：允许其他任务只读
